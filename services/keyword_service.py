import os
import logging
import time
import json
import re
import textwrap
from typing import List, Dict, Set, Any

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from openai import OpenAI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def _normalize_kw(kw: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    if kw is None:
        return ""
    return re.sub(r"\s+", " ", str(kw).strip()).lower()


def _safe_truncate_to_sentence(text: str, limit: int) -> str:
    """Truncate text at sentence boundary using textwrap.shorten for nicer truncation."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    try:
        return textwrap.shorten(text, width=limit, placeholder="...")
    except Exception:
        return text[:limit] + "..."


class StreamlinedKeywordAgent:
    """
    A streamlined keyword agent following the exact pipeline:
    1. Extract seed keywords from scraped data
    2. Get Google Ads suggestions in chunks
    3. Deduplicate all suggestions
    4. Optimize keywords with match types
    5. Generate negative keywords from optimized positives
    """

    def __init__(self):
        self.setup_apis()

    def setup_apis(self):
        """Setup API clients with proper error handling."""
        try:
            # OpenAI setup
            openai_key = os.getenv("OPENAI_API_KEY")
            if not openai_key:
                raise ValueError("OPENAI_API_KEY is required")
            self.openai_client = OpenAI(api_key=openai_key)

            # Google Ads setup
            google_ads_config = {
                "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
                "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
                "login_customer_id": os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
                "use_proto_plus": True,
            }

            missing_creds = [k for k, v in google_ads_config.items(
            ) if not v and k != "login_customer_id"]
            if missing_creds:
                raise ValueError(
                    f"Missing Google Ads credentials: {missing_creds}")

            self.google_ads_client = GoogleAdsClient.load_from_dict(
                google_ads_config)
            logger.info("Successfully initialized API clients")
        except Exception as e:
            logger.exception("Failed to setup APIs: %s", e)
            raise

    def extract_positive_keywords_llm(self, scraped_data: Dict, url: str = None, max_kw: int = 50) -> List[str]:
        """
        STEP 1: Extract seed keywords from scraped JSON data using LLM.
        Returns list of normalized keyword strings for Google Ads API input.
        """
        try:
            # Extracted structured content
            structured_content = scraped_data

            prompt = f"""
                You are a Google Ads keyword research specialist. Extract seed keywords from this website data to use for Google Ads Keyword Planner API.

                    WEBSITE DATA:
                    URL: {url or 'Not provided'}
                    {_safe_truncate_to_sentence(structured_content, 3500)}

                    TASK: Extract {max_kw} seed keywords that will be used to generate more keyword ideas via Google Ads API.

                    SEED KEYWORD CRITERIA:
                    1. CORE BUSINESS TERMS: Main products, services, solutions offered
                    2. INDUSTRY KEYWORDS: Relevant industry and category terms
                    3. PROBLEM-SOLVING TERMS: What issues the business solves
                    4. LOCATION TERMS: If local business, include city/area names
                    5. ACTION WORDS: Services like "hire", "buy", "get", "find"
                    6. VARIATIONS: Include synonyms and related terms

                    REQUIREMENTS:
                    - Each keyword should be 1-4 words maximum
                    - Focus on broad seed terms that can generate more specific suggestions
                    - Include both generic and specific business terms
                    - Return ONLY a clean JSON array of strings
                    - No explanations, just the keyword array

                    EXAMPLE OUTPUT:
                    ["web design", "digital marketing", "seo services", "website development"]
            """

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content.strip()

            # Parse JSON response
            parsed = []
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("LLM returned non-list")
            except Exception:
                # Fallback parsing
                parts = re.split(r'[\n,•;]+', raw)
                parsed = [p.strip().strip('"\'') for p in parts if p.strip()]

            # Normalize and deduplicate
            normalized = []
            seen = set()
            for kw in parsed:
                if not isinstance(kw, str):
                    continue
                k = _normalize_kw(kw)
                if len(k) < 2 or len(k) > 80:
                    continue
                if k not in seen:
                    normalized.append(k)
                    seen.add(k)

            logger.info(
                "Extracted %d seed keywords for Google Ads API", len(normalized))
            return normalized[:max_kw]

        except Exception as e:
            logger.exception("Seed keyword extraction failed: %s", e)
            return []

    def get_google_ads_suggestions(
        self,
        customer_id: str,
        seed_keywords: List[str],
        url: str = None,
        location_id: int = 2840,
        language_id: int = 1000,
        chunk_size: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        STEP 2: Get keyword suggestions from Google Ads API in chunks.
        Returns deduplicated list of suggestions with metrics.
        """
        try:
            ga_service = self.google_ads_client.get_service("GoogleAdsService")
            service = self.google_ads_client.get_service(
                "KeywordPlanIdeaService")

            all_suggestions: List[Dict[str, Any]] = []
            seen_keywords: Set[str] = set()

            # Process seed keywords in chunks
            for i in range(0, len(seed_keywords), chunk_size):
                chunk = seed_keywords[i: i + chunk_size]
                logger.info("Processing Google Ads chunk %d/%d (size=%d)",
                            i // chunk_size + 1,
                            (len(seed_keywords) + chunk_size - 1) // chunk_size,
                            len(chunk))

                try:
                    request = self.google_ads_client.get_type(
                        "GenerateKeywordIdeasRequest")
                    request.customer_id = customer_id

                    # Set language
                    try:
                        request.language = ga_service.language_constant_path(
                            language_id)
                    except Exception:
                        request.language_constant = ga_service.language_constant_path(
                            language_id)

                    # Set geo targeting
                    try:
                        request.geo_target_constants.append(
                            ga_service.geo_target_constant_path(location_id))
                    except Exception:
                        request.geo_target_constants.extend(
                            [ga_service.geo_target_constant_path(location_id)])

                    request.include_adult_keywords = False
                    request.keyword_plan_network = (
                        self.google_ads_client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH_AND_PARTNERS
                    )

                    # Set seed keywords
                    if url:
                        request.keyword_and_url_seed.keywords.extend(chunk)
                        request.keyword_and_url_seed.url = str(url).strip()
                    else:
                        request.keyword_seed.keywords.extend(chunk)

                    # Make API call with retries
                    response = None
                    for attempt in range(3):
                        try:
                            response = service.generate_keyword_ideas(
                                request=request)
                            break
                        except GoogleAdsException as ex:
                            logger.warning(
                                "Google Ads API error on attempt %d: %s", attempt + 1, ex)
                            time.sleep(2 ** attempt)

                    if not response:
                        logger.warning(
                            "No response from Google Ads API for chunk %d", i // chunk_size + 1)
                        continue

                    # Process response
                    chunk_count = 0
                    for kw_idea in response:
                        try:
                            # Extract keyword text
                            text_val = getattr(kw_idea, "text", None) or getattr(
                                kw_idea, "keyword", None)
                            if not text_val:
                                continue

                            text_norm = _normalize_kw(text_val)
                            if text_norm in seen_keywords or len(text_norm) < 2:
                                continue

                            seen_keywords.add(text_norm)

                            # Extract metrics
                            metrics = getattr(
                                kw_idea, "keyword_idea_metrics", None) or {}

                            volume = 0
                            try:
                                volume = int(
                                    getattr(metrics, "avg_monthly_searches", 0) or 0)
                            except Exception:
                                volume = 0

                            competition = "UNKNOWN"
                            try:
                                comp_obj = getattr(
                                    metrics, "competition", None)
                                if comp_obj and hasattr(comp_obj, "name"):
                                    competition = comp_obj.name
                                else:
                                    competition = str(
                                        comp_obj) if comp_obj else "UNKNOWN"
                            except Exception:
                                competition = "UNKNOWN"

                            competition_index = 0.0
                            try:
                                ci_raw = getattr(
                                    metrics, "competition_index", None)
                                if ci_raw is not None:
                                    competition_index = float(
                                        ci_raw) / 100.0 if ci_raw > 1 else float(ci_raw)
                            except Exception:
                                competition_index = 0.0

                            # Filter quality keywords
                            if volume >= 10 and len(text_norm.split()) <= 6:
                                all_suggestions.append({
                                    "keyword": text_norm,
                                    "volume": volume,
                                    "competition": competition,
                                    "competitionIndex": float(competition_index),
                                })
                                chunk_count += 1

                        except Exception as e:
                            logger.debug(
                                "Error processing keyword idea: %s", e)
                            continue

                    logger.info("Got %d suggestions from chunk %d",
                                chunk_count, i // chunk_size + 1)

                    # Rate limiting between chunks
                    if i + chunk_size < len(seed_keywords):
                        time.sleep(1)

                except Exception as e:
                    logger.exception(
                        "Failed to process chunk %d: %s", i // chunk_size + 1, e)
                    continue

            logger.info("TOTAL: Got %d deduplicated suggestions from Google Ads API", len(
                all_suggestions))
            return all_suggestions

        except Exception as e:
            logger.exception("Google Ads suggestions failed: %s", e)
            return []


    def optimize_keywords_with_llm(
        self,
        all_suggestions: List[Dict[str, Any]],
        scraped_data: Dict,
        url: str = None,
        target_count: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        STEP 3: Optimize keywords from all suggestions and assign match types.
        Returns list of dicts with keyword, metrics, and match_type.
        """
        try:
            if not all_suggestions:
                logger.warning("No suggestions provided for optimization")
                return []

            # Extract business context
            structured_content = scraped_data

            # Prepare keyword data for LLM analysis
            # Sort by ROI potential value (ROI = volume/competition ratio)
            sorted_suggestions = sorted(
                all_suggestions,
                key=lambda x: x.get("volume", 0) /
                (1 + x.get("competitionIndex", 0.0)),
                reverse=True
            )

            keyword_data = []
            for s in sorted_suggestions:
                k = s.get("keyword", "")
                v = int(s.get("volume", 0) or 0)
                c = s.get("competition", "UNKNOWN")
                ci = float(s.get("competitionIndex", 0.0) or 0.0)
                roi_score = v / (1 + ci) if ci else v
                keyword_data.append(
                    f"{k} | Vol:{v} | Comp:{c} | CI:{ci:.2f} | ROI:{roi_score:.0f}")

            keywords_text = "\n".join(keyword_data)

            prompt = f"""You are a Google Ads optimization expert. Analyze these keyword suggestions and select EXACTLY the best {target_count} keywords for a profitable campaign.

                BUSINESS CONTEXT:
                URL: {url or 'Not provided'}
                {_safe_truncate_to_sentence(structured_content, 1000)}

                KEYWORD SUGGESTIONS WITH METRICS:
                {keywords_text}

                SELECTION CRITERIA (prioritized):
                1. HIGH COMMERCIAL INTENT (40%): Buying signals (buy, hire, price, cost, service, professional, company, solutions)
                2. VOLUME-TO-COMPETITION RATIO (30%): High ROI potential (prefer Vol>500, CI<0.7)
                3. BUSINESS RELEVANCE (20%): Must match business offerings
                4. KEYWORD QUALITY (10%): 2-4 words, specific intent

                MATCH TYPE ASSIGNMENT RULES:
                - EXACT: [keyword] - High commercial intent, specific services (use sparingly, 20%)
                - PHRASE: "keyword" - Good balance, main services (use most, 60%)
                - BROAD: keyword - Discovery, related terms (use carefully, 20%)

                QUALITY GUIDELINES:
                - Include mix of high-volume (>1000) and targeted long-tail keywords
                - Balance between broad reach and specific intent
                - Prefer keywords with clear buying intent
                - Include location-based if business is local
                - Dont include duplicate keywords

                OUTPUT REQUIREMENTS:
                Return a JSON object with this exact structure:
                    {{
                        "keywords": [
                            {{"keyword": "web design services", "match_type": "PHRASE", "rationale": "High commercial intent with good volume"}},
                            {{"keyword": "hire web designer", "match_type": "EXACT", "rationale": "Strong buying signal"}}
                        ]
                    }}
                Select exactly {target_count}  UNIQUE keywords with match types (EXACT, PHRASE, or BROAD)."""

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=5000,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            raw = resp.choices[0].message.content.strip()

            # Parse LLM response
            try:
                response_data = json.loads(raw)
                optimized_list = response_data.get("keywords", [])

                if not isinstance(optimized_list, list):
                    raise ValueError("Expected JSON array")

            except Exception as e:
                logger.warning(
                    "Failed to parse LLM optimization response: %s", e)

                # Todo instead of the getting from suggestions should use the custom function to parse llm output
                # Fallback: take top suggestions by ROI
                optimized_list = []
                for i, s in enumerate(sorted_suggestions[:target_count]):
                    match_type = "phrase"  # Default
                    if i < target_count * 0.2:  # Top 20% as exact
                        match_type = "exact"
                    elif i > target_count * 0.8:  # Bottom 20% as broad
                        match_type = "broad"

                    optimized_list.append({
                        "keyword": s["keyword"],
                        "match_type": match_type,
                        "rationale": "Fallback selection"
                    })

            # Map back to original suggestion data and create final list
            suggestion_map = {s["keyword"].lower(): s for s in all_suggestions}
            final_optimized = []
            # tracking to avoid duplicates because llm returning same keyword different rationale
            seen_optimized = set()

            for item in optimized_list:
                if not isinstance(item, dict):
                    continue

                kw = _normalize_kw(item.get("keyword", ""))
                match_type = item.get("match_type", "phrase").lower()
                rationale = item.get(
                    "rationale", "Selected by llm optimization")

                if not kw:
                    continue

                if kw.lower() in seen_optimized:  # skipping if already seen this keyword
                    continue

                seen_optimized.add(kw.lower())

                # Find matching suggestion data
                suggestion_data = suggestion_map.get(kw)
                if not suggestion_data:
                    # Try partial match with more strict criteria
                    for original_key, original_data in suggestion_map.items():
                        if (kw.lower() in original_key or original_key in kw.lower()) and \
                                abs(len(kw) - len(original_key)) <= 3:  # Length difference threshold
                            suggestion_data = original_data
                            break

                if not suggestion_data:
                    # Create fallback data
                    continue

                # Ensure valid match type
                if match_type not in ["exact", "phrase", "broad"]:
                    match_type = "phrase"

                final_optimized.append({
                    "keyword": suggestion_data["keyword"],
                    "volume": suggestion_data["volume"],
                    "competition": suggestion_data["competition"],
                    "competitionIndex": suggestion_data["competitionIndex"],
                    "match_type": match_type,
                    "rationale": rationale
                })

                if len(final_optimized) >= target_count:
                    break
            final_optimized = sorted(
                final_optimized, key=lambda x: x["volume"], reverse=True)
            logger.info("Optimized %d keywords with match types",
                        len(final_optimized))
            return final_optimized

        except Exception as e:
            logger.exception("Keyword optimization failed: %s", e)
            # Return fallback selection
            try:
                sorted_suggestions = sorted(
                    all_suggestions,
                    key=lambda x: x.get("volume", 0) /
                    (1 + x.get("competitionIndex", 0.0)),
                    reverse=True
                )
                fallback = []
                for s in sorted_suggestions[:target_count]:
                    s["match_type"] = "phrase"
                    s["rationale"] = "Fallback selection"
                    fallback.append(s)
                return fallback
            except Exception:
                return []

    def generate_negative_keywords_llm(self, optimized_positive_keywords: List[Dict[str, Any]], scraped_data: Dict, url: str = None) -> List[Dict[str, Any]]:
        """
        STEP 4: Generate negative keywords based on optimized positive keywords.
        Takes the final positive keywords to understand what to exclude.
        """
        try:
            # Extract business context
            structured_content = scraped_data

            # Extract positive keywords for context
            positive_kw_list = [kw.get("keyword", "")
                                for kw in optimized_positive_keywords]
            # Providing sample positive keywords as string of comma seperated
            positive_keywords_text = ", ".join(positive_kw_list)

            # prompt = f"""You are a Google Ads specialist focused on preventing wasted ad spend through strategic negative keywords.

            #         BUSINESS CONTEXT:
            #         URL: {url or 'Not provided'}
            #         {_safe_truncate_to_sentence(structured_content, 2000)}

            #         SELECTED POSITIVE KEYWORDS (for context):
            #         {positive_keywords_text}

            #         TASK: Generate negative keywords to exclude irrelevant traffic and protect ad budget.

            #         NEGATIVE KEYWORD CATEGORIES:
            #         1. COMPETITOR BRANDS: Major competitors in the industry
            #         2. IRRELEVANT INTENT:
            #         - "free", "cheap", "discount" if premium service
            #         - "diy", "tutorial", "how to" if selling professional services
            #         - "jobs", "career", "hiring" if targeting customers not job seekers
            #         3. WRONG SERVICE TYPE: Services/products NOT offered by this business
            #         4. UNQUALIFIED AUDIENCE:
            #         - "student", "beginner", "amateur" if targeting professionals
            #         - Age/demographic mismatches
            #         5. GEOGRAPHIC EXCLUSIONS: Areas not served (if applicable)
            #         6. IRRELEVANT INDUSTRIES: Industries not served
            #         7. INFORMATIONAL QUERIES: Non-commercial search intent

            #         ANALYSIS APPROACH:
            #         - Review the business model and target audience
            #         - Identify what the business does NOT offer
            #         - Consider who should NOT see these ads
            #         - Think about search terms that waste budget

            #         OUTPUT:
            #         Return a JSON object with this exact structure:
            #             {{
            #                 "negative_keywords": [
            #                     {{"keyword": "free", "reason": "Excludes users seeking free solutions"}},
            #                     {{"keyword": "diy", "reason": "Excludes do-it-yourself seekers"}}
            #                 ]
            #             }}

            #         Generate exactly 50 negative keywords that will improve campaign ROI:"""

            prompt = f"""
                        You are a Google Ads specialist focused on preventing wasted ad spend through strategic negative keywords.

                    BUSINESS CONTEXT:
                    URL: {url or 'Not provided'}
                    {_safe_truncate_to_sentence(structured_content, 2000)}

                    SELECTED POSITIVE KEYWORDS (for context):
                    {positive_keywords_text}

                    TASK: Generate negative keywords to exclude irrelevant traffic and protect ad budget.

                    NEGATIVE KEYWORD CATEGORIES:
                    1. COMPETITOR BRANDS: Major competitors in the industry
                    2. IRRELEVANT INTENT:
                    - "free", "cheap", "discount" if premium service
                    - "diy", "tutorial", "how to" if selling professional services
                    - "jobs", "career", "hiring" if targeting customers not job seekers
                    3. WRONG SERVICE TYPE: Services/products NOT offered by this business
                    4. UNQUALIFIED AUDIENCE:
                    - "student", "beginner", "amateur" if targeting professionals
                    - Age/demographic mismatches
                    5. GEOGRAPHIC EXCLUSIONS: Areas not served (if applicable)
                    6. IRRELEVANT INDUSTRIES: Industries not served
                    7. INFORMATIONAL QUERIES: Non-commercial search intent

                    IMPORTANT RULES (per Google Ads documentation):
                    - Each negative keyword must be 16 words or fewer.
                    - Avoid invalid special characters: ! @ % , *
                    - Negative keywords do NOT match close variants, so include common plural/singular or misspelling variations when appropriate.
                    - Avoid duplicates.
                    - Do not over-restrict: ensure the list excludes irrelevant queries but does not block qualified leads.

                    ANALYSIS APPROACH:
                    - Review the business model and target audience
                    - Identify what the business does NOT offer
                    - Consider who should NOT see these ads
                    - Think about search terms that waste budget

                    OUTPUT:
                    Return a JSON object with this exact structure:
                    {{
                "negative_keywords": [
                        {{"keyword": "free", "reason": "Excludes users seeking free solutions"}},
                        {{"keyword": "diy", "reason": "Excludes do-it-yourself seekers"}}
                    ]
                    }}

                    Generate up to 50 high-quality negative keywords that will improve campaign ROI while complying with Google Ads rules.

            """

            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content.strip()

            # Parse JSON response
            try:
                response_data = json.loads(raw)
                negatives = response_data.get("negative_keywords", [])
                if not isinstance(negatives, list):
                    raise ValueError("Expected JSON array")
            except Exception as e:
                logger.warning(
                    "Failed JSON parse for negatives, using fallback: %s", e)
                # Fallback parsing
                lines = raw.split('\n')
                negatives = []
                for line in lines:
                    if ':' in line and not line.strip().startswith('#'):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            kw = parts[0].strip().strip('"\'')
                            reason = parts[1].strip()
                            negatives.append({"keyword": kw, "reason": reason})

            # Clean and validate negative keywords
            safety_patterns = [
                r"http[s]?://", r"\.com", r"\.net", r"\.org",
                r"^\d+$", r"(xxx|porn|adult|sex)", r"^\s*$"
            ]

            cleaned_negatives = []
            seen = set()

            for item in negatives:
                if not isinstance(item, dict):
                    continue

                kw = _normalize_kw(item.get("keyword", ""))
                reason = item.get("reason", "").strip() or "Budget protection"

                # just basic filtering for avoid the short and long negative keyword in list
                if not kw or len(kw) < 2 or len(kw) > 50:
                    continue

                # Apply safety filters
                if any(re.search(p, kw, re.IGNORECASE) for p in safety_patterns):
                    continue

                # Avoid duplicates
                if kw in seen:
                    continue

                # Don't negate our own positive keywords
                pos_tokens = set()
                for pos in positive_kw_list:
                    for t in re.findall(r"\w+", pos.lower()):
                        pos_tokens.add(t)
                kw_tokens = set(re.findall(r"\w+", kw.lower()))

                if kw_tokens & pos_tokens:
                    if len(kw_tokens) <= 2 or kw in [p.lower()for p in positive_kw_list]:
                        continue

                seen.add(kw)
                cleaned_negatives.append({
                    "keyword": kw,
                    "reason": reason
                })

            logger.info("Generated %d negative keywords",
                        len(cleaned_negatives))
            return cleaned_negatives

        except Exception as e:
            logger.error(f"Negative keyword generation failed: %s", e)
            return []

    def run_full_pipeline(
        self,
        scraped_data: Dict,
        customer_id: str,
        url: str = None,
        location_id: int = 2840,
        language_id: int = 1000,
        seed_count: int = 50,
        target_positive_count: int = 50
    ) -> Dict[str, Any]:
        """
        Execute the complete pipeline and return both positive and negative keywords.

        Returns:
        {
            "positive_keywords": [{"keyword": str, "volume": int, "competition": str, "competitionIndex": float, "match_type": str, "rationale": str}],
            "negative_keywords": [{"keyword": str, "reason": str}]
        }
        """
        start_time = time.time()
        logger.info("Starting full keyword research pipeline")

        try:
            # STEP 1: Extract seed keywords from scraped data
            logger.info("STEP 1: Extracting seed keywords from scraped data")
            seed_keywords = self.extract_positive_keywords_llm(
                scraped_data, url, seed_count)
            if not seed_keywords:
                logger.error("No seed keywords extracted")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 2: Get Google Ads suggestions in chunks
            logger.info("STEP 2: Getting Google Ads suggestions for %d seed keywords", len(
                seed_keywords))
            all_suggestions = self.get_google_ads_suggestions(
                customer_id=customer_id,
                seed_keywords=seed_keywords,
                url=url,
                location_id=location_id,
                language_id=language_id
            )
            if not all_suggestions:
                logger.error("No suggestions from Google Ads API")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 3: Optimize keywords with match types
            logger.info("STEP 3: Optimizing %d suggestions to %d keywords", len(
                all_suggestions), target_positive_count)
            optimized_positive = self.optimize_keywords_with_llm(
                all_suggestions=all_suggestions,
                scraped_data=scraped_data,
                url=url,
                target_count=target_positive_count
            )
            if not optimized_positive:
                logger.error("No keywords optimized")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 4: Generate negative keywords
            logger.info("STEP 4: Generating negative keywords based on %d positive keywords", len(
                optimized_positive))
            negative_keywords = self.generate_negative_keywords_llm(
                optimized_positive_keywords=optimized_positive,
                scraped_data=scraped_data,
                url=url
            )

            result = {
                "positive_keywords": optimized_positive,
                "negative_keywords": negative_keywords
            }

            logger.info("Pipeline completed: %d positive, %d negative keywords",
                        len(optimized_positive), len(negative_keywords))

            end_time = (time.time() - start_time) * 1000
            print(end_time)

            return result

        except Exception as e:
            logger.exception("Full pipeline failed: %s", e)
            return {"positive_keywords": [], "negative_keywords": []}


# ------------ USAGE EXAMPLE ------------
if __name__ == "__main__":
    # Example scraped data structure
    sample_scraped_data = """
            Harrison Legal Group focuses on meeting the complex legal needs of creative professionals across arts, entertainment, and media sectors. 
            The firm’s practice areas include intellectual property protection such as copyrights, trademarks, and trade secrets, 
            ensuring clients can secure and enforce their creative works. They also provide legal counsel for intentional torts like defamation, 
            privacy rights, and publicity rights, alongside specialized services for digital media issues including artificial intelligence content, 
            online takedown notices, and combating unfair online reviews.The firm handles a wide range of contractual matters, from production 
            and distribution agreements to employment contracts and studio leases, offering legal support tailored to every stage of a client’s career or project.
            Harrison Legal Group emphasizes personalized service, aiming to make legal processes approachable and clear by keeping clients informed 
            and involved with customized solutions designed for their unique situations.Known for its deep expertise and significant track record, 
            the firm leverages a broad network within legal and media industries to drive favorable outcomes and efficient resolution of disputes. Clients
            benefit from dedicated representation focused on achieving the best possible results and gaining peace of mind from knowing their legal affairs are in experienced hands.
            Additionally, Harrison Legal Group offers a no-cost contract evaluation for agreements up to 10 pages, which includes a detailed review, 
            answers to key questions, and advice on potential risks and unique opportunities. Follow-up consultations are available via phone, video, 
            or in-person meetings, demonstrating the firm’s commitment to accessible, client-focused legal care.Overall, 
            Harrison Legal Group stands as a trusted legal partner for creative professionals seeking expert guidance in protecting their rights, 
            resolving disputes, and navigating the complexities of entertainment and media law.
        """

    # Initialize the agent
    agent = StreamlinedKeywordAgent()

    # Run the complete pipeline
    CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "your-customer-id")
    URL_SEED = "https://harrisonlegalgroup.com"

    # Execute pipeline
    result = agent.run_full_pipeline(
        scraped_data=sample_scraped_data,
        customer_id=CUSTOMER_ID,
        url=URL_SEED,
        seed_count=40,
        target_positive_count=50
    )
    print("==========printing the results=============")
    print(result)
