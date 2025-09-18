import os
import logging
import time
import json
import re
import textwrap
from typing import List, Dict, Set, Any

from functools import lru_cache

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from openai import OpenAI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@lru_cache(maxsize=1000)
def _normalize_kw_cached(kw: str) -> str:
    """Cached version of keyword normalization for better performance."""
    if kw is None:
        return ""
    return re.sub(r"\s+", " ", str(kw).strip()).lower()


def _normalize_kw(kw: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return _normalize_kw_cached(kw)


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


class AIKeywordAgent:
    """
    An streamlined keyword agent with performance improvements.
    """

    def __init__(self):
        self.setup_apis()
        # Pre-compile regex patterns for better performance
        self.safety_patterns = [
            re.compile(r"http[s]?://", re.IGNORECASE),
            re.compile(r"\.com", re.IGNORECASE),
            re.compile(r"\.net", re.IGNORECASE),
            re.compile(r"\.org", re.IGNORECASE),
            re.compile(r"^\d+$"),
            re.compile(r"(xxx|porn|adult|sex)", re.IGNORECASE),
            re.compile(r"^\s*$")
        ]

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

            missing_credentials = [k for k, v in google_ads_config.items() if not v and k != "login_customer_id"]
            if missing_credentials:
                raise ValueError(
                    f"Missing Google Ads credentials: {missing_credentials}")

            self.google_ads_client = GoogleAdsClient.load_from_dict(google_ads_config)
            
        except Exception as e:
            logger.exception("Failed to setup APIs: %s", e)
            raise

    def extract_positive_keywords_llm(self, scraped_data: str, url: str = None, max_kw: int = 50) -> List[str]:
        """
        STEP 1: Extract seed keywords from scraped JSON data using LLM.
                Returns list of normalized keyword strings for Google Ads API input.
        """
        try:
            content_summary = _safe_truncate_to_sentence(
                str(scraped_data), 2500)

            prompt = f"""You are a Google Ads keyword research specialist.

                WEBSITE DATA:
                URL: {url or 'Not provided'}
                {content_summary}

                TASK: Extract up to {max_kw} high-quality seed keywords covering:
                1. CORE BUSINESS: Main products/services offered
                2. INDUSTRY TERMS: Relevant category/industry keywords
                3. PROBLEM-SOLVING: Issues the business addresses
                4. LOCATION: City/area names if local business
                5. ACTION WORDS: "hire", "buy", "get", "find" services
                6. VARIATIONS: Synonyms and related terms

                Requirements:
                - Each keyword must be 1–4 words maximum
                - Focus ONLY on terms directly relevant to this specific business model
                - include the business name if required
                - EXCLUDE:
                        * Competitor brand names
                        * Overly generic words (e.g., "services", "company")
                        * Unrelated industries or irrelevant topics
                - Each keyword must be something a qualified customer might search for to buy THIS business’s offering

                OUTPUT:
                Return **only** a valid JSON array of strings. No explanations, no extra text.

                Example output:
                ["web design", "digital marketing", "seo services", "website development"]
                """

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
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
                # Simplified fallback parsing
                parts = re.findall(r'"([^"]+)"', raw)
                if not parts:
                    parts = re.split(r'[\n,•;]+', raw)
                parsed = [p.strip().strip('"\'') for p in parts if p.strip()]

            # Optimized normalization and deduplication
            normalized = []
            seen = set()
            for kw in parsed[:max_kw * 2]:  # Process more to account for filtering
                if not isinstance(kw, str):
                    continue
                k = _normalize_kw(kw)
                if 2 <= len(k) <= 80 and k not in seen:
                    normalized.append(k)
                    seen.add(k)
                if len(normalized) >= max_kw:
                    break

            logger.info("Extracted %d seed keywords", len(normalized))
            return normalized

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
        chunk_size: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        STEP 2: Get keyword suggestions from Google Ads API with optimizations.
        """
        try:
            ga_service = self.google_ads_client.get_service("GoogleAdsService")
            service = self.google_ads_client.get_service(
                "KeywordPlanIdeaService")

            all_suggestions: List[Dict[str, Any]] = []
            seen_keywords: Set[str] = set()

            # Process seeds in their natural order (as extracted by LLM)
            # Process in optimized chunks
            total_chunks = (len(seed_keywords) +
                            chunk_size - 1) // chunk_size

            for i in range(0, len(seed_keywords), chunk_size):
                chunk = seed_keywords[i: i + chunk_size]
                chunk_num = i // chunk_size + 1

                logger.info("Processing chunk %d/%d (size=%d)",
                            chunk_num, total_chunks, len(chunk))

                try:
                    request = self.google_ads_client.get_type(
                        "GenerateKeywordIdeasRequest")
                    request.customer_id = customer_id

                    # Set language and geo targeting
                    try:
                        request.language = ga_service.language_constant_path(
                            language_id)
                        request.geo_target_constants.append(
                            ga_service.geo_target_constant_path(location_id))
                    except Exception:
                        request.language_constant = ga_service.language_constant_path(
                            language_id)
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

                    # API call with retries
                    response = None
                    for attempt in range(2):  # retrying with max 2 times
                        try:
                            response = service.generate_keyword_ideas(
                                request=request)
                            break
                        except GoogleAdsException as ex:
                            logger.warning(
                                "API error attempt %d: %s", attempt + 1, str(ex)[:100])
                            if attempt == 0:
                                time.sleep(1)

                    if not response:
                        logger.warning("No response for chunk %d", chunk_num)
                        continue

                    # Optimized response processing with early filtering
                    chunk_suggestions = []
                    for kw_idea in response:
                        try:
                            text_val = getattr(kw_idea, "text", None) or getattr(
                                kw_idea, "keyword", None)
                            if not text_val:
                                continue

                            text_norm = _normalize_kw(text_val)
                            if text_norm in seen_keywords or len(text_norm) < 2 or len(text_norm.split()) > 6:
                                continue

                            # Extract metrics
                            metrics = getattr(
                                kw_idea, "keyword_idea_metrics", None) or {}

                            try:
                                volume = int(
                                    getattr(metrics, "avg_monthly_searches", 0) or 0)
                            except:
                                volume = 0

                            # Early filter for quality - only process high-potential keywords
                            if volume < 10:  # Skip very low volume keywords early
                                continue

                            try:
                                comp_obj = getattr(
                                    metrics, "competition", None)
                                competition = comp_obj.name if comp_obj and hasattr(
                                    comp_obj, "name") else "UNKNOWN"
                            except:
                                competition = "UNKNOWN"

                            try:
                                ci_raw = getattr(
                                    metrics, "competition_index", None)
                                competition_index = float(
                                    ci_raw) / 100.0 if ci_raw and ci_raw > 1 else float(ci_raw or 0)
                            except:
                                competition_index = 0.0

                            seen_keywords.add(text_norm)
                            chunk_suggestions.append({
                                "keyword": text_norm,
                                "volume": volume,
                                "competition": competition,
                                "competitionIndex": competition_index,
                            })

                        except Exception as e:
                            logger.debug(
                                "Error processing keyword: %s", str(e)[:50])
                            continue

                    # Sort chunk by ROI potential and take top performers
                    chunk_suggestions.sort(
                        key=lambda x: x["volume"] / (1 + x["competitionIndex"]), reverse=True)
                    # Limit per chunk to manage size
                    all_suggestions.extend(chunk_suggestions[:100])

                    logger.info("Got %d quality suggestions from chunk %d", len(
                        chunk_suggestions), chunk_num)

                    # Rate limiting between chunks
                    if i + chunk_size < len(seed_keywords):
                        time.sleep(0.5)

                except Exception as e:
                    logger.exception("Failed chunk %d: %s", chunk_num, str(e)[:100])
                    continue

            # Final deduplication and sorting
            final_suggestions = []
            seen_final = set()
            all_suggestions.sort(
                key=lambda x: x["volume"] / (1 + x["competitionIndex"]), reverse=True)

            for suggestion in all_suggestions:
                kw = suggestion["keyword"]
                if kw not in seen_final:
                    final_suggestions.append(suggestion)
                    seen_final.add(kw)
                if len(final_suggestions) >= 300:  # Sending  the top 300 limit for optimization step
                    break

            logger.info("TOTAL: %d deduplicated suggestions from google ads api",
                        len(final_suggestions))
            return final_suggestions

        except Exception as e:
            logger.exception("Google Ads suggestions failed: %s", e)
            return []

    def optimize_keywords_with_llm(
        self,
        all_suggestions: List[Dict[str, Any]],
        scraped_data: str,
        url: str = None,
        target_count: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        STEP 3: HEAVILY OPTIMIZED keyword optimization.
        MAJOR OPTIMIZATIONS:
        1. Pre-filter suggestions to reduce LLM input size
        2. Simplified prompt structure
        3. Reduced context size
        4. Smart keyword selection algorithm
        """
        try:
            if not all_suggestions:
                logger.warning("No suggestions for optimization")
                return []

            # PURE GOOGLE ADS DATA APPROACH - No arbitrary classifications!
            # Sort by ROI potential using actual market data
            roi_sorted = sorted(
                all_suggestions,
                key=lambda x: x.get("volume", 0) /
                (1 + x.get("competitionIndex", 0.0)),
                reverse=True
            )

            # GOOGLE'S MARKET INTELLIGENCE - Let the data speak
            if len(all_suggestions) <= target_count * 2:
                selected_candidates = roi_sorted
            else:
                # Use Google's Competition Index as the commercial intent indicator
                # High CI = More advertisers bidding = Market-validated commercial value

                logger.info(
                    "Using Google Ads market data for keyword selection...")

                # Segment by ACTUAL market competition (Google's data)
                high_market_competition = []    # CI >= 0.6 - Heavy advertiser competition
                medium_market_competition = []  # 0.3 <= CI < 0.6 - Moderate competition
                low_market_competition = []     # CI < 0.3 - Less competitive

                for suggestion in roi_sorted:
                    ci = suggestion.get("competitionIndex", 0.0)
                    if ci >= 0.6:
                        high_market_competition.append(suggestion)
                    elif ci >= 0.3:
                        medium_market_competition.append(suggestion)
                    else:
                        low_market_competition.append(suggestion)

                # Volume-based segmentation (market demand validation)
                high_demand = [
                    s for s in roi_sorted if s.get("volume", 0) >= 1000]
                medium_demand = [
                    s for s in roi_sorted if 300 <= s.get("volume", 0) < 1000]
                low_demand = [
                    s for s in roi_sorted if s.get("volume", 0) < 300]

                # MARKET-DRIVEN SELECTION STRATEGY
                max_candidates = min(target_count * 3, len(roi_sorted))
                selected_candidates = []
                seen_keywords = set()

                # Strategy 1: High-value opportunities (good volume + manageable competition)
                balanced_opportunities = [s for s in roi_sorted if s.get(
                    "volume", 0) >= 500 and s.get("competitionIndex", 0) <= 0.7]

                for candidate in balanced_opportunities[:max_candidates // 4]:
                    if candidate["keyword"] not in seen_keywords:
                        selected_candidates.append(candidate)
                        seen_keywords.add(candidate["keyword"])

                # Strategy 2: Market-validated commercial terms (high competition = commercial value)
                for candidate in high_market_competition:
                    if len(selected_candidates) >= max_candidates * 0.4:  # Limit to 40%
                        break
                    if candidate["keyword"] not in seen_keywords:
                        selected_candidates.append(candidate)
                        seen_keywords.add(candidate["keyword"])

                # Strategy 3: High-demand terms (market-proven volume)
                for candidate in high_demand:
                    if len(selected_candidates) >= max_candidates * 0.6:  # Limit to 60%
                        break
                    if candidate["keyword"] not in seen_keywords:
                        selected_candidates.append(candidate)
                        seen_keywords.add(candidate["keyword"])

                # Strategy 4: Medium-demand terms (balanced opportunities)
                for candidate in medium_demand:
                    if len(selected_candidates) >= max_candidates * 0.8:  # Limit to 80%
                        break
                    if candidate["keyword"] not in seen_keywords:
                        selected_candidates.append(candidate)
                        seen_keywords.add(candidate["keyword"])

                # Strategy 5: Low-demand/long-tail terms (specific intent)
                for candidate in low_demand:
                    if len(selected_candidates) >= max_candidates * 0.9:  # Limit to 90%
                        break
                    if candidate["keyword"] not in seen_keywords:
                        selected_candidates.append(candidate)
                        seen_keywords.add(candidate["keyword"])

                # Strategy 6: Fill remaining with best ROI performers
                remaining = [c for c in roi_sorted if c["keyword"] not in seen_keywords]
                for candidate in remaining:
                    if len(selected_candidates) >= max_candidates:
                        break
                    selected_candidates.append(candidate)
                    seen_keywords.add(candidate["keyword"])

            # Build COMPREHENSIVE keyword analysis for LLM with REAL market signals
            keyword_analysis = []
            for s in selected_candidates:
                kw = s.get("keyword", "")
                vol = s.get("volume", 0)
                comp = s.get("competition", "UNKNOWN")
                ci = s.get("competitionIndex", 0.0)
                roi = vol / (1 + ci) if ci else vol

                # Add market intelligence context
                market_signals = []
                if ci >= 0.7:
                    # Strong commercial competition
                    market_signals.append("HIGH_COMP")
                if vol >= 1000:
                    market_signals.append("HIGH_VOL")  # Proven demand
                if roi >= 1000:
                    market_signals.append("HIGH_ROI")  # Excellent opportunity
                if len(kw.split()) >= 3:
                    market_signals.append("LONG_TAIL")  # Specific intent

                signals_text = ",".join(
                    market_signals) if market_signals else "STANDARD"

                # Rich context for LLM analysis
                keyword_analysis.append(
                    f"{kw} | Vol:{vol} | Comp:{comp} | CI:{ci:.2f} | ROI:{roi:.0f} | Signals:[{signals_text}]")

            keywords_text = "\n".join(keyword_analysis)

            # ENHANCED business context with intent analysis guidance
            business_summary = _safe_truncate_to_sentence(
                str(scraped_data), 1200)

            prompt = f"""
                You are a Google Ads strategist analyzing keywords with REAL market data. 
                Select EXACTLY {target_count} keywords using data-driven insights.

                BUSINESS CONTEXT:
                URL: {url or 'Not provided'}
                {business_summary}

                KEYWORD DATA WITH MARKET SIGNALS:
                {keywords_text}

                MARKET SIGNAL DEFINITIONS:
                - HIGH_COMP: High competition (CI≥0.7) = Market-validated commercial value
                - HIGH_VOL: High volume (≥1000) = Proven search demand
                - HIGH_ROI: High ROI score (≥1000) = Volume/competition sweet spot
                - LONG_TAIL: 3+ words = Specific user intent

                INTELLIGENT SELECTION CRITERIA:

                1. STRICT BUSINESS RELEVANCE (50%):
                - **ONLY** include keywords that directly match the specific products, services, or solutions mentioned in the BUSINESS CONTEXT.
                - **LOCATION FILTERING**: Include location-based keywords ONLY if:
                    • Business explicitly mentions serving specific cities/regions, OR
                    • Business context indicates local/regional service area, OR
                    • Business mentions "near me" or local service delivery
                - **INDUSTRY BOUNDARIES**: Exclude keywords from unrelated industries, even if they share similar terms
                - **SERVICE SCOPE**: If business offers "A and B", don't include keywords for "C, D, E"
                - **AUDIENCE FILTERING**: Exclude keywords targeting demographics not mentioned in business context
                - When in doubt about relevance, EXCLUDE the keyword

                2. MARKET-VALIDATED VALUE (25%): Use competition index as commercial intent indicator.
                - High CI (≥0.5) often means commercial value.
                - Low CI with high volume = opportunity gaps.

                3. PERFORMANCE POTENTIAL (15%):
                - Prioritize HIGH_ROI signals.
                - Balance reach (HIGH_VOL) vs competition.

                4. INTENT DIVERSITY (10%):
                - Include a mix of specific (LONG_TAIL) and broad terms.
                - Ensure all terms align with business-stated customer journey stages

                MATCH TYPE STRATEGY:
                - EXACT: High competition + clear commercial intent + perfect business fit (20%)
                - PHRASE: Balanced performance potential + strong business alignment (60%)
                - BROAD: Discovery opportunities + still directly relevant to stated business scope (20%)

                5. QUALITY GUIDELINES:
                **INCLUDE ONLY IF:**
                - Directly matches stated products/services
                - Fits declared target audience
                - Matches business geographic scope (if any specified)
                - Aligns with business model (B2B vs B2C vs marketplace, etc.)
                - Represents genuine customer search behavior for THIS business

                **EXCLUDE KEYWORDS FOR:**
                - Services/products NOT mentioned in business context
                - Locations outside stated service area
                - Demographics not mentioned as target audience
                - Competitor brand names
                - Job/career terms (unless HR/recruiting business)
                - Educational/informational terms (unless educational business)
                - "Free", "cheap", "discount" (unless discount/budget business model)
                - Industry terms for different industries
                - Generic terms that could apply to any business
                - Terms requiring capabilities not mentioned in business context
                - Vacation rentals, holidays, resorts, homestays (unless the business is explicitly offering short-term stays)
                - Construction/builders services (unless business context states construction service)

                **VALIDATION CHECK:**
                Before including any keyword, ask: "Would someone searching this term be specifically looking for what THIS business offers based on the business context provided?"

                OUTPUT FORMAT:
                Return only valid JSON object in this structure:
                {{
                "keywords": [
                    {{"keyword": "legal consultation", "match_type": "phrase", "rationale": "High competition (0.8 CI), strong service alignment, matches stated legal services"}},
                    {{"keyword": "entertainment lawyer near me", "match_type": "exact", "rationale": "Long-tail with high commercial signals, direct business fit, location appropriate for stated local service area"}}
                ]
                }}

                Return exactly {target_count} keywords in the array — no more, no less.
                Each rationale must explain WHY the keyword fits the specific business context provided.
        """

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            raw = resp.choices[0].message.content.strip()

            # Parse and map back to suggestion data
            try:
                response_data = json.loads(raw)
                optimized_list = response_data.get("keywords", [])
            except Exception as e:
                logger.warning(
                    "JSON parse failed, using algorithmic fallback: %s", e)

                # FAST ALGORITHMIC FALLBACK
                optimized_list = []
                for i, s in enumerate(selected_candidates[:target_count]):
                    match_type = "phrase"
                    if i < target_count * 0.2:
                        match_type = "exact"
                    elif i > target_count * 0.8:
                        match_type = "broad"

                    optimized_list.append({
                        "keyword": s["keyword"],
                        "match_type": match_type
                    })

            # Quick mapping back to suggestion data
            suggestion_map = {s["keyword"]: s for s in selected_candidates}
            final_optimized = []
            seen = set()

            for item in optimized_list:
                if not isinstance(item, dict):
                    continue

                kw = _normalize_kw(item.get("keyword", ""))
                match_type = item.get("match_type", "phrase").lower()
                rationale = item.get("rationale", "AI optimized")

                if not kw or kw in seen:
                    continue

                seen.add(kw)
                suggestion_data = suggestion_map.get(kw)

                if suggestion_data:
                    final_optimized.append({
                        **suggestion_data,
                        "match_type": match_type if match_type in ["exact", "phrase", "broad"] else "phrase",
                        # "rationale": "LLM optimized selection"
                        "rationale": rationale if rationale else "AI Optimized Selected"
                    })

                if len(final_optimized) >= target_count:
                    break

            # Final sort by volume
            final_optimized.sort(key=lambda x: x["volume"], reverse=True)
            logger.info("Optimized to %d keywords", len(final_optimized))
            return final_optimized

        except Exception as e:
            logger.exception("Optimization failed: %s", e)
            # Quick fallback
            try:
                fallback = []
                for s in roi_sorted[:target_count]:
                    fallback.append(
                        {**s, "match_type": "phrase", "rationale": "Fallback selection"})
                return fallback
            except:
                return []

    def generate_negative_keywords_llm(self, optimized_positive_keywords: List[Dict[str, Any]], scraped_data: str, url: str = None) -> List[Dict[str, Any]]:
        """
        STEP 4: Negative keyword generation.
        """
        try:
            # Compact business context
            business_summary = _safe_truncate_to_sentence(
                str(scraped_data), 1000)

            # Simple positive keyword list
            positive_terms = [kw.get("keyword", "") for kw in optimized_positive_keywords]
            positive_text = ",".join(positive_terms)

            prompt = f"""
                        You are a Google Ads negative-keyword strategist. Your task is to generate a tailored list of negative keywords to prevent irrelevant or wasteful ad spend for the business described below.

                    INPUT:
                    URL: {url or 'Not provided'}
                    BUSINESS SUMMARY: {business_summary}
                    POSITIVE KEYWORDS (for context): {positive_text}

                    PROCESS:
                    1. Analyze the business summary, the website (if URL provided), and the positive keywords to identify:
                    - Core offerings and services/products
                    - Primary audiences (students, freelancers, professionals, businesses, etc.)
                    - Pricing/positioning (premium, budget, free, trial)
                    - Geography (local/national/global)
                    - Any explicit exclusions

                    2. Based on this analysis, generate **negative keyword categories dynamically**. Possible categories (only include those that fit): competitor brands, job seekers, free/cheap/discount, DIY/tutorials, reviews/comparisons, wrong industries, non-commercial informational searches, geography not served.

                    3. To guarantee campaign protection, always include **at least 20 high-quality negatives** by supplementing with broad universal waste-traffic terms if fewer are identified from context. Universal categories may include:
                    - Price-sensitive: free, cheap, discount, trial, demo, sample, cracked
                    - Informational: tutorial, how to, guide, pdf, download
                    - Misaligned intent: jobs, career, hiring, support, customer service
                    - Comparative: reviews, alternatives, competitors, comparison

                    4. When generating negatives:
                    - Do NOT exclude queries overlapping with POSITIVE KEYWORDS.
                    - Do NOT exclude valid audiences explicitly mentioned in the business summary (e.g., students, freelancers).
                    - Stay conservative: if uncertain, do not exclude.
                    - Each keyword ≤ 16 words, no invalid characters (! @ % , *).

                    OUTPUT:
                    Return exactly one JSON object in this format:
                    {{
                    "negative_keywords": [
                        {{ "keyword": "string", "reason": "Category: <category> — short rationale" }},
                        ...
                    ]
                    }}

                    Generate **between 20 and 50** negative keywords, mixing business-specific and universal categories, ensuring strong coverage without blocking qualified traffic.

                """
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content.strip()

            try:
                response_data = json.loads(raw)
                negatives = response_data.get("negative_keywords", [])
                #print("negatives", negatives)
            except Exception as e:
                logger.error(f"Negative keyword generation failed: {e}")
                logger.info("Returning the fallback negatives")
                fallback_negatives = [
                    {"keyword": "free", "reason": "Universal budget-waster"},
                    {"keyword": "cheap", "reason": "Universal budget-waster"},
                    {"keyword": "trial", "reason": "Universal budget-waster"},
                    {"keyword": "demo", "reason": "Universal budget-waster"},
                    {"keyword": "sample", "reason": "Universal budget-waster"},
                    {"keyword": "jobs", "reason": "Universal intent filter"},
                    {"keyword": "career", "reason": "Universal intent filter"},
                    {"keyword": "hiring", "reason": "Universal intent filter"},
                    {"keyword": "tutorial", "reason": "Universal intent filter"},
                    {"keyword": "how to", "reason": "Universal intent filter"},
                    {"keyword": "pdf", "reason": "Universal informational filter"},
                    {"keyword": "download", "reason": "Universal informational filter"},
                    {"keyword": "cracked", "reason": "Universal piracy filter"},
                    {"keyword": "alternatives", "reason": "Universal comparison filter"},
                    {"keyword": "reviews", "reason": "Universal comparison filter"},
                    {"keyword": "comparison", "reason": "Universal comparison filter"},
                ]
                negatives = fallback_negatives

            cleaned = []
            seen = set()

            positive_tokens = set()
            for pos in positive_terms:
                positive_tokens.update(re.findall(r"\w+", pos.lower()))

            for item in negatives:
                if not isinstance(item, dict):
                    continue

                kw = _normalize_kw(item.get("keyword", ""))
                reason = item.get("reason", "Budget protection")

                if not kw or len(kw) < 2 or len(kw) > 50 or kw in seen:
                    continue

                # Fast safety check
                if any(pattern.search(kw) for pattern in self.safety_patterns):
                    continue

                # Quick positive keyword overlap check
                kw_tokens = set(re.findall(r"\w+", kw.lower()))

                if kw in [p.lower() for p in positive_terms]:
                    continue

                overlap_ratio = len(
                    kw_tokens & positive_tokens) / max(len(kw_tokens), 1)

                if overlap_ratio >= 0.7:
                    continue

                seen.add(kw)
                cleaned.append({"keyword": kw, "reason": reason})

                if len(cleaned) >= 50:  # Reasonable limit
                    break

            logger.info("Generated %d negative keywords", len(cleaned))
            return cleaned

        except Exception as e:
            logger.error(f"Negative keyword generation failed: {e}")
            return []

    def run_keywords_pipeline(
        self,
        scraped_data: str,
        customer_id: str,
        url: str = None,
        location_id: int = 2840,
        language_id: int = 1000,
        seed_count: int = 40,  # Reduced default
        target_positive_count: int = 50
    ) -> Dict[str, Any]:
        """
        Execute the complete pipeline.
        """
        start_time = time.time()
        logger.info("Starting OPTIMIZED keyword research pipeline")

        try:
            # STEP 1: Extract seed keywords
            logger.info("STEP 1: Extracting seed keywords")
            seed_start = time.time()
            seed_keywords = self.extract_positive_keywords_llm(
                scraped_data, url, seed_count)
            logger.info("Step 1 completed in %.2f seconds",
                        time.time() - seed_start)

            if not seed_keywords:
                logger.error("No seed keywords extracted")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 2: Get Google Ads suggestions
            logger.info(
                "STEP 2: Getting Google Ads suggestions for %d seeds", len(seed_keywords))
            suggestions_start = time.time()
            all_suggestions = self.get_google_ads_suggestions(
                customer_id=customer_id,
                seed_keywords=seed_keywords,
                url=url,
                location_id=location_id,
                language_id=language_id
            )
            logger.info("Step 2 completed in %.2f seconds",
                        time.time() - suggestions_start)

            if not all_suggestions:
                logger.error("No suggestions from Google Ads API")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 3: Optimize positive keywords
            logger.info("STEP 3: Optimizing %d suggestions to %d keywords", len(
                all_suggestions), target_positive_count)
            optimization_start = time.time()
            optimized_positive = self.optimize_keywords_with_llm(
                all_suggestions=all_suggestions,
                scraped_data=scraped_data,
                url=url,
                target_count=target_positive_count
            )
            optimization_time = time.time() - optimization_start
            logger.info("Step 3 completed in %.2f seconds", optimization_time)

            if not optimized_positive:
                logger.error("No keywords optimized")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 4: Generate negatives keywords
            logger.info("STEP 4: Generating negative keywords")
            negatives_start = time.time()
            negative_keywords = self.generate_negative_keywords_llm(
                optimized_positive_keywords=optimized_positive,
                scraped_data=scraped_data,
                url=url
            )
            logger.info("Step 4 completed in %.2f seconds",
                        time.time() - negatives_start)

            result = {
                "positive_keywords": optimized_positive,
                "negative_keywords": negative_keywords
            }

            total_time = time.time() - start_time
            logger.info("OPTIMIZED pipeline completed in %.2f seconds: %d positive, %d negative keywords",
                        total_time, len(optimized_positive), len(negative_keywords))

            return result

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return {"positive_keywords": [], "negative_keywords": []}
        

    def run_positive_pipeline(
        self,
        scraped_data: str,
        customer_id: str,
        url: str = None,
        location_id: int = 2840,
        language_id: int = 1000,
        seed_count: int = 40,
        target_positive_count: int = 50
    ) -> Dict[str, Any]:
        """
        Execute the complete pipeline.
        """
        start_time = time.time()

        logger.info("Starting Positive keyword pipeline")

        try:
            # STEP 1: Extract seed keywords
            logger.info("STEP 1: Extracting seed keywords")

            seed_keywords = self.extract_positive_keywords_llm(
                scraped_data, url, seed_count)
            
            if not seed_keywords:
                logger.error("No seed keywords extracted")
                return {"positive_keywords": []}

            # STEP 2: Get Google Ads suggestions
            logger.info("STEP 2: Getting Google Ads suggestions for %d seeds", len(seed_keywords))
            
            all_suggestions = self.get_google_ads_suggestions(
                customer_id=customer_id,
                seed_keywords=seed_keywords,
                url=url,
                location_id=location_id,
                language_id=language_id
            )

            if not all_suggestions:
                logger.error("No suggestions from Google Ads API")
                return {"positive_keywords": []}

            # STEP 3: Optimize positive keywords
            logger.info("STEP 3: Optimizing %d suggestions to %d keywords", len(all_suggestions), target_positive_count)
            
            optimized_positive = self.optimize_keywords_with_llm(
                all_suggestions=all_suggestions,
                scraped_data=scraped_data,
                url=url,
                target_count=target_positive_count
            )


            if not optimized_positive:
                logger.error("No keywords optimized")
                return {"positive_keywords": []}

            result = {
                "positive_keywords": optimized_positive,
            }

            total_time = time.time() - start_time
            logger.info("Positive pipeline completed in %.2f seconds: %d positive",
                        total_time, len(optimized_positive))

            return result

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return {"positive_keywords": []}
        
    def run_negative_pipeline(
        self,
        optimized_positive_keywords: List[Dict[str, Any]],
        scraped_data: str,
        url: str = None,
    ) -> Dict[str, Any]:
        """
        Execute the complete pipeline.
        """
        negatives_start = time.time()

        logger.info("Starting Negative keyword pipeline")

        try:
            logger.info("Generating negative keywords pipeline started")
            negatives_start = time.time()

            negative_keywords = self.generate_negative_keywords_llm(
                optimized_positive_keywords=optimized_positive_keywords,
                scraped_data=scraped_data,
                url=url
            )

            logger.info("Step 4 completed in %.2f seconds",
                        time.time() - negatives_start)
            
            result = {
                "negative_keywords": negative_keywords,
            }

            return result

        except Exception as e:
            logger.exception("Negative pipeline failed: %s", e)
            return {"negative_keywords": []}



