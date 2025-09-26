import os
import logging
import time
import requests
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
    Improved keyword agent with strategic filtering pipeline.
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

            # Google Ads developer token (only need this for direct API calls)
            developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
            if not developer_token:
                raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")
            
        except Exception as e:
            logger.exception("Failed to setup APIs: %s", e)
            raise

    def extract_brand_info_from_content(self, scraped_data: str, url: str = None) -> Dict[str, Any]:
        """
        Extract brand name and location info from business content dynamically.
        """
        try:
            content_summary = _safe_truncate_to_sentence(str(scraped_data), 2000)
            
            prompt = f"""
                    You are a precise business analyst extracting factual information. Adhere strictly to the following rules:

                    **CRITICAL CONSTRAINTS:**
                    - Extract ONLY information explicitly stated in the content
                    - DO NOT infer, assume, or guess any information
                    - If information is not clearly stated, use the specified default values
                    - Never add information not present in the text

                    **BUSINESS CONTENT ANALYSIS:**
                    URL: {url or 'Not provided'}
                    CONTENT: {content_summary}

                    **EXTRACTION TASKS:**
                    1. **Brand/Business Name**: Exact company, project, or brand name explicitly mentioned
                    2. **Primary Location**: Main city/area explicitly stated as business base/headquarters
                    3. **Service Areas**: Only geographic areas explicitly mentioned as service locations
                    4. **Business Type**: Main industry/category explicitly described

                    **EXPLICIT INSTRUCTIONS:**
                    - For brand names: Extract only names that are clearly identified as the main business entity
                    - For locations: Only use locations that are explicitly stated, not implied
                    - For service areas: List only areas that are specifically mentioned as served
                    - For business type: Use the most specific category explicitly described

                    **UNCERTAINTY HANDLING:**
                    - If any field cannot be confidently extracted from explicit content, use:
                    - "Unknown" for text fields
                    - Empty list [] for service_areas
                    - When uncertain, prefer "Unknown" over making assumptions
                    - If content is insufficient or ambiguous, default to uncertainty values

                    **OUTPUT REQUIREMENTS:**
                    - Return ONLY valid JSON, no additional text
                    - Use exact phrasing from content when possible
                    - For brand_keywords: generate 2-5 common search variations based ONLY on the extracted brand name

                    **STRICT OUTPUT FORMAT:**
                    {{
                        "brand_name": "Exact name or 'Unknown'",
                        "primary_location": "Explicit location or 'Unknown'",
                        "service_areas": ["explicit", "locations", "only"],
                        "business_type": "Explicit category or 'Unknown'",
                        "brand_keywords": ["variation1", "variation2"]
                    }}

                    **REMINDER: Zero tolerance for hallucination. Extract only what is explicitly stated.**
                    """
                                
            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.0,  # Zero temperature to reduce hallucination
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content.strip()
            brand_info = json.loads(raw)
            
            # Validate extracted data
            if not brand_info.get("brand_name"):
                brand_info["brand_name"] = "Unknown"
            if not brand_info.get("primary_location"):
                brand_info["primary_location"] = "Unknown"
            if not isinstance(brand_info.get("service_areas"), list):
                brand_info["service_areas"] = []
            if not isinstance(brand_info.get("brand_keywords"), list):
                brand_info["brand_keywords"] = []
                
            logger.info(f"Extracted brand info: {brand_info}")
            return brand_info
            
        except Exception as e:
            logger.warning(f"Brand extraction failed: {e}")
            return {
                "brand_name": "Unknown",
                "primary_location": "Unknown", 
                "service_areas": [],
                "business_type": "Unknown",
                "brand_keywords": []
            }

    def extract_unique_features(self, scraped_data: str) -> List[str]:
        """Extract unique features/USPs with anti-hallucination measures."""
        content_summary = _safe_truncate_to_sentence(str(scraped_data), 1500)
        
        usp_prompt = f"""
                You are a factual feature extractor. Extract ONLY unique features, amenities, or selling points that are EXPLICITLY stated in the business content.

                **CRITICAL RULES:**
                - Extract ONLY features that are directly mentioned in the text
                - DO NOT infer, assume, or imagine any features not explicitly stated
                - If no clear features are mentioned, return an empty array
                - Never add features based on general knowledge or common expectations

                **CONTENT TO ANALYZE:**
                {scraped_data}

                **EXTRACTION GUIDELINES:**
                - Look for concrete, specific features that are presented as selling points
                - Focus on tangible amenities, services, or unique attributes explicitly described
                - Avoid generic marketing language unless it specifies concrete features
                - Extract only what is clearly stated as a feature/amenity/USP

                **EXPLICIT EXAMPLES OF ACCEPTABLE FEATURES:**
                - "clay tiles", "co-working spaces", "home automation", "infinity pool"
                - "4 BHK apartments", "garden villa", "eco-friendly materials"
                - "24/7 security", "swimming pool", "modular kitchen"

                **WHAT TO EXCLUDE:**
                - Generic claims without specific features ("excellent quality", "best service")
                - Implied benefits not stated as features
                - Common industry standards that aren't highlighted as unique
                - Anything not explicitly mentioned in the content

                **UNCERTAINTY HANDLING:**
                - When in doubt, leave it out
                - If content is too vague or marketing-heavy without specific features, return empty array
                - Prefer false negatives (missing actual features) over false positives (adding imaginary features)

                **STRICT OUTPUT FORMAT:**
                Return the valid JSON OBJECT
                {{
                    "features": ["explicitly", "stated", "features", "only"]
                }}

                **REMINDER: Zero tolerance for hallucination. If no specific features are explicitly stated, return: {{"features": []}}**
                """

        try:
            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": usp_prompt}],
                max_tokens=250,
                temperature=0.0,  # Zero temperature
                response_format={"type": "json_object"}
            )
            usp_data = json.loads(resp.choices[0].message.content.strip())
            unique_features = [str(f).lower().strip() for f in usp_data.get("features", []) 
                             if isinstance(f, str) and len(str(f).strip()) > 0]
            
            # Limit to prevent over-extraction
            unique_features = unique_features[:8]
            
            logger.info(f"Extracted USPs: {unique_features}")
        except Exception as e:
            logger.warning(f"USP extraction failed: {e}")
            unique_features = []

        return unique_features

    def generate_strategic_seeds(self, scraped_data: str, url: str = None, brand_info: Dict[str, Any] = None, unique_features: List[str] = None, max_kw: int = 40) -> List[str]:
        """
        Generate strategic seed keywords combining brand + services + locations.
        """
        try:
            content_summary = _safe_truncate_to_sentence(str(scraped_data), 2000)
            
            brand_name = brand_info.get("brand_name", "Unknown")
            primary_location = brand_info.get("primary_location", "Unknown")
            service_areas = brand_info.get("service_areas", [])
            business_type = brand_info.get("business_type", "Unknown")

            # Build location context
            location_context = ""
            if primary_location != "Unknown":
                location_context += f"Primary Location: {primary_location}\n"
            if service_areas:
                location_context += f"Service Areas: {', '.join(service_areas)}\n"

            # Build features context
            features_context = ""
            if unique_features:
                features_context = f"Unique Features: {', '.join(unique_features)}\n"

            prompt = f"""
                You are a universal keyword strategist for Google Ads and SEO. Generate seed keywords for ANY business type.

                BUSINESS CONTEXT:
                URL: {url or 'Not provided'}
                Content Summary: {content_summary}

                BUSINESS METADATA:
                - Brand: {brand_name}
                - Business Type: {business_type}
                {location_context}{features_context}

                TASK: Generate {max_kw} diverse, high-intent seed keywords that real customers would search for.

                KEYWORD STRATEGY (adapt to business type):
                1. **Core Offerings**: [main service/product] + location/context
                2. **Solution-Based**: [problem] + [solution] + location
                3. **Feature-Focused**: [unique feature] + [service] + context  
                4. **Comparative**: [service] vs alternatives + location
                5. **Intent-Driven**: "buy/hire/find/get" + [service] + location
                6. **Lifestyle/Aspirational**: Quality/benefit-focused phrases

                UNIVERSAL KEYWORD PATTERNS TO CONSIDER:
                - "[service] near [location/landmark]"
                - "best [service] for [use case]"
                - "[service] with [feature]"
                - "affordable/premium [service] [location]"
                - "[service] for [target audience]"
                - "how to choose [service]"
                - "[service] prices/costs/reviews"

                ADAPTATION GUIDELINES:
                - For SERVICES: focus on "hire", "find", "get", "book", "contact"
                - For PRODUCTS: focus on "buy", "price", "where to buy", "review"  
                - For B2B: focus on "vendor", "supplier", "solution", "provider"
                - For LOCAL BUSINESS: emphasize location, "near me", area-specific
                - For E-COMMERCE: focus on "online", "shop", "delivery", "buy online"

                STRICT RULES:
                - Use ONLY information provided above - no external knowledge
                - Keywords should be 2-6 words maximum
                - Mix short-tail (broad) and long-tail (specific) keywords
                - Include both transactional and informational intent
                - Ensure geographic relevance when locations are provided
                - If brand is known, include 3-5 brand variations maximum
                - Avoid generic, low-intent terms like "good service" or "nice product"

                SPECIFIC CONSTRAINTS:
                - Brand known: {brand_name != "Unknown"}
                - Locations available: {primary_location != "Unknown" or len(service_areas) > 0}
                - Features available: {len(unique_features) > 0 if unique_features else False}

                OUTPUT: Return ONLY valid JSON array: ["keyword1", "keyword2", ...]
                """

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content.strip()

            # Parse JSON response with robust error handling
            parsed = []
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("Response not a list")
            except Exception:
                # Fallback parsing
                parts = re.findall(r'"([^"]+)"', raw)
                if not parts:
                    parts = re.split(r'[\n,•;]+', raw)
                parsed = [p.strip().strip('"\'') for p in parts if p.strip()]

            # Normalize and deduplicate
            normalized = []
            seen = set()
            for kw in parsed:
                if not isinstance(kw, str):
                    continue
                k = _normalize_kw(kw)
                if 2 <= len(k) and k not in seen:
                    normalized.append(k)
                    seen.add(k)

            # Count brand keywords for logging
            brand_count = 0
            if brand_name != "Unknown":
                brand_count = sum(1 for kw in normalized if brand_name.lower() in kw.lower())

            logger.info(f"Generated {len(normalized)} strategic seeds ({brand_count} brand keywords)")
            return normalized[:max_kw]

        except Exception as e:
            logger.exception("Strategic seed generation failed: %s", e)
            return []

    def get_google_ads_suggestions(
        self,
        customer_id: str,
        seed_keywords: List[str],
        access_token: str,
        url: str = None,
        location_ids :List[str] = None,
        language_id: int = 1000,
        chunk_size: int = 15,
        brand_info: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get keyword suggestions using direct gRPC API calls with access token.
        Supports multiple location targeting.
        """
        
        
        try:
            # Default to India if no locations provided
            if location_ids is None or len(location_ids) == 0:
                location_ids = ["geoTargetConstants/2840"]  # India
            
            all_suggestions: List[Dict[str, Any]] = []
            seen_keywords: Set[str] = set()

            def is_brand_keyword(keyword: str) -> bool:
                if not brand_info:
                    return False
                
                brand_name = brand_info.get("brand_name", "").lower()
                brand_keywords = brand_info.get("brand_keywords", [])

                if brand_name == "unknown" or not brand_name:
                    return False
                
                keyword_lower = keyword.lower()
                if brand_name in keyword_lower:
                    return True
                return any(brand_kw.lower() in keyword_lower for brand_kw in brand_keywords if brand_kw)
            
            if brand_info:
                logger.info(f"Brand protection enabled for: {brand_info.get('brand_name', 'Unknown')}")

            # Google Ads API endpoint
            developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
            if not developer_token:
                raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")
            
            endpoint = f"https://googleads.googleapis.com/v21/customers/{customer_id}/keywordPlanIdeas:generate"

            if access_token is None:
                access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")
            
            # Headers for API call
            headers = {
                "Authorization": f"Bearer {access_token}",
                "developer-token": developer_token,
                "Content-Type": "application/json"
            }

            logger.info(f"Targeting {len(location_ids)} locations: {location_ids}")

            # Process in chunks
            total_chunks = (len(seed_keywords) + chunk_size - 1) // chunk_size

            for i in range(0, len(seed_keywords), chunk_size):
                chunk = seed_keywords[i: i + chunk_size]
                chunk_num = i // chunk_size + 1

                logger.info("Processing chunk %d/%d (size=%d)", chunk_num, total_chunks, len(chunk))

                try:
                    # Build request payload with multiple locations
                    payload = {
                        "language": f"languageConstants/{language_id}",
                        "geoTargetConstants": [f"{loc_id}" for loc_id in location_ids],
                        "includeAdultKeywords": False,
                        "keywordPlanNetwork": "GOOGLE_SEARCH_AND_PARTNERS"
                    }
                    
                    # Set seed keywords
                    if url and url.strip():
                        payload["keywordAndUrlSeed"] = {
                            "keywords": chunk,
                            "url": str(url).strip()
                        }
                    else:
                        payload["keywordSeed"] = {
                            "keywords": chunk
                        }

                    # API call with retries
                    response = None
                    for attempt in range(2):
                        try:
                            response = requests.post(
                                endpoint,
                                headers=headers,
                                json=payload,
                                timeout=30
                            )
                            
                            if response.status_code == 200:
                                break
                            else:
                                logger.warning(f"API error attempt {attempt + 1}: {response.status_code} - {response.text[:200]}")
                                if attempt == 0:
                                    time.sleep(1)
                                    
                        except requests.exceptions.RequestException as ex:
                            logger.warning(f"Request error attempt {attempt + 1}: {str(ex)[:100]}")
                            if attempt == 0:
                                time.sleep(1)

                    if not response or response.status_code != 200:
                        logger.warning(f"No valid response for chunk {chunk_num}")
                        continue

                    # Parse JSON response
                    response_data = response.json()
                    results = response_data.get("results", [])
                    
                    if not results:
                        logger.info(f"No results in chunk {chunk_num}")
                        continue

                    # Process response with brand protection
                    chunk_suggestions = []
                    for kw_idea in results:
                        try:
                            text_val = kw_idea.get("text", "")
                            if not text_val:
                                continue

                            text_norm = _normalize_kw(text_val)
                            if text_norm in seen_keywords or len(text_norm) < 2 or len(text_norm.split()) > 6:
                                continue

                            # Extract metrics
                            metrics = kw_idea.get("keywordIdeaMetrics", {})

                            try:
                                volume = int(metrics.get("avgMonthlySearches", 0))
                            except (ValueError, TypeError):
                                volume = 0

                            # Brand keyword protection - don't filter by volume
                            if is_brand_keyword(text_norm):
                                logger.info(f"Brand keyword protected: {text_norm} (volume: {volume})")
                            
                            try:
                                competition = metrics.get("competition", "UNKNOWN")
                            except:
                                competition = "UNKNOWN"

                            try:
                                competition_index = float(metrics.get("competitionIndex", 0)) / 100.0
                            except (ValueError, TypeError):
                                competition_index = 0.0

                            seen_keywords.add(text_norm)
                            chunk_suggestions.append({
                                "keyword": text_norm,
                                "volume": volume,
                                "competition": competition,
                                "competitionIndex": competition_index,
                            })

                        except Exception as e:
                            logger.debug("Error processing keyword: %s", str(e)[:50])
                            continue

                    all_suggestions.extend(chunk_suggestions)
                    logger.info("Got %d quality suggestions from chunk %d", len(chunk_suggestions), chunk_num)

                    # Rate limiting between chunks
                    if i + chunk_size < len(seed_keywords):
                        time.sleep(0.5)

                except Exception as e:
                    logger.exception("Failed chunk %d: %s", chunk_num, str(e)[:100])
                    continue

            # Final deduplication and sorting
            final_suggestions = []
            seen_final = set()
            all_suggestions.sort(key=lambda x: x["volume"], reverse=True)

            for suggestion in all_suggestions:
                kw = suggestion["keyword"]
                if kw not in seen_final:
                    final_suggestions.append(suggestion)
                    seen_final.add(kw)
                if len(final_suggestions) >= 300:
                    break

            logger.info("TOTAL: %d suggestions from Google Ads API for %d locations", len(final_suggestions), len(location_ids))
            return final_suggestions

        except Exception as e:
            logger.exception("Google Ads suggestions failed: %s", e)
            return []

    def optimize_for_intent_and_match_types(
        self,
        all_suggestions: List[Dict[str, Any]],
        business_info: Dict[str, Any],
        unique_features: List[str],
        scraped_data: str,
        url: str = None,
        target_count: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Final LLM optimization focusing on buying intent and match type assignment.
        """
        try:
            # Prepare data for LLM with clear categorization
            keyword_data = []
            for s in all_suggestions:
                kw = s.get("keyword", "")
                vol = s.get("volume", 0)
                comp =s.get("competitionIndex",0.0)
                roi = vol / (1 + s.get("competitionIndex", 0.0))
                
                keyword_data.append(f"{kw} | Volume:{vol} | ROI:{roi:.0f} | Competition: {comp:.2f} ")
            
            keywords_text = "\n".join(keyword_data)
            business_summary = _safe_truncate_to_sentence(str(scraped_data), 2500)

            prompt = f"""You are a Google Ads specialist selecting keywords with STRONG BUYING INTENT for a paid search campaign.

                BUSINESS CONTEXT:
                Brand: {business_info.get("brand_name", "Unknown")}
                Business Type: {business_info.get("business_type", "Unknown")}
                Primary Location: {business_info.get("primary_location", "Unknown")}
                Unique Features: {", ".join(unique_features) if unique_features else "None"}

                Business Summary: {business_summary}
                Url :{url}

                AVAILABLE KEYWORDS (Keyword | Volume | ROI | competitionIndex):
                {keywords_text}

                SELECTION CRITERIA:
                1. **MANDATORY INCLUSIONS**:
                - ALL keywords marked as Type:BRAND (essential for brand visibility)
                - ALL keywords marked as Type:USP (unique business features)

                2. **BUYING INTENT FOCUS**:
                - Prioritize keywords indicating purchase readiness
                - Commercial terms: "buy", "price", "for sale", "cost", location-specific searches
                - Avoid purely informational terms unless they show commercial context

                3. **BUSINESS RELEVANCE**:
                - Select keywords that closely match the actual business offerings described in the business summary
                - Ensure geographic relevance if location is specified

                MATCH TYPE ASSIGNMENT STRATEGY:
                - **EXACT MATCH (40%)**: All BRAND keywords + highest commercial intent terms
                - **PHRASE MATCH (60%)**: Core service/product terms with good intent signals
                - **BROAD MATCH (20%)**: Discovery and awareness terms

                STRICT REQUIREMENTS:
                - Select EXACTLY {target_count} keywords
                - Include ALL BRAND and USP type keywords (non-negotiable)
                - Use ONLY keywords from the provided list above

                Return ONLY valid JSON:
                {{
                    "keywords": [
                        {{"keyword": "exact text from list above", "match_type": "exact", "rationale": "Brand keyword with commercial intent"}},
                        {{"keyword": "exact text from list above", "match_type": "phrase", "rationale": "Core service term with good intent"}}
                    ]
                }}"""

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                temperature=0.0,  # Zero temperature for consistency
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content.strip()
            response_data = json.loads(raw)
            optimized_list = response_data.get("keywords", [])
            
            # Map back to original suggestion data
            suggestion_map = {s["keyword"]: s for s in all_suggestions}
            final_optimized = []
            seen = set()
            
            for item in optimized_list:
                kw = _normalize_kw(item.get("keyword", ""))
                if kw in suggestion_map and kw not in seen:
                    final_optimized.append({
                        **suggestion_map[kw],
                        "match_type": item.get("match_type", "phrase"),
                        "rationale": item.get("rationale", "AI selected")
                    })
                    seen.add(kw)
            
            # Ensure we have the target count
            if len(final_optimized) < target_count:
                remaining = [s for s in all_suggestions if s["keyword"] not in seen]
                for s in remaining[:target_count - len(final_optimized)]:
                    final_optimized.append({
                        **s,
                        "match_type": "phrase",
                        "rationale": "Fallback selection"
                    })
            
            logger.info(f"Final optimization: {len(final_optimized)} keywords selected")
            return final_optimized[:target_count]
            
        except Exception as e:
            logger.exception("Intent optimization failed: %s", e)
            # Fallback to simple selection
            fallback = []
            for i, s in enumerate(all_suggestions[:target_count]):
                match_type = "exact" if i < target_count * 0.3 else ("phrase" if i < target_count * 0.6 else "broad")
                fallback.append({
                    **s,
                    "match_type": match_type,
                    "rationale": "Fallback selection"
                })
            return fallback

    def generate_negative_keywords_llm(self, optimized_positive_keywords: List[Dict[str, Any]], scraped_data: str, url: str = None) -> List[Dict[str, Any]]:
        """
        Generate negative keywords with improved anti-hallucination measures and business context awareness.
        """
        try:
            business_summary = _safe_truncate_to_sentence(str(scraped_data), 1000)
            positive_terms = [kw.get("keyword", "") for kw in optimized_positive_keywords]
            positive_text = ", ".join(positive_terms[:25])

            prompt = f"""You are a Google Ads specialist preventing wasted ad spend through strategic negative keywords.

                    BUSINESS CONTEXT:
                    URL: {url or 'Not provided'}
                    Business Description: {business_summary}
                    Current Positive Keywords: {positive_text}

                    TASK: Generate 25-35 negative keywords to block irrelevant traffic that would waste ad budget.

                    NEGATIVE KEYWORD STRATEGY:

                    1. ANALYZE THE BUSINESS FIRST:
                    - What does this business actually sell/offer?
                    - Who is their target customer?
                    - What price tier do they operate in?
                    - What related but different services/products should be excluded?

                    2. MANDATORY UNIVERSAL NEGATIVES (Include these):
                    - "free" (unless business offers free services)
                    - "cheap" (unless budget-focused business)
                    - "jobs", "career", "hiring", "employment" (unless HR/recruitment)
                    - "tutorial", "how to", "diy" (unless educational business)
                    - "download", "software", "app" (unless tech/software business)

                    3. BUSINESS-SPECIFIC NEGATIVES (Based on the business description):
                    - Wrong industries/sectors not served
                    - Competitor brand names (if clearly different market)
                    - Wrong customer segments (B2B vs B2C mismatch)
                    - Wrong geographic areas (if location-specific business)
                    - Wrong price points (luxury vs budget mismatch)

                    4. INTENT NEGATIVES:
                    - Information-only searches that won't convert
                    - Wrong purchase stage (research vs ready-to-buy)
                    - Wrong use cases not served by the business

                    CRITICAL RULES:
                    - Do NOT exclude terms that could bring qualified traffic
                    - Do NOT exclude variations of your positive keywords
                    - Do NOT exclude legitimate customer search terms
                    - Focus on clear mismatches between search intent and business offering
                    - Keep negative keywords under 3 words each

                    QUALITY CHECK:
                    - Would someone searching this negative keyword EVER be a good customer?
                    - Does this negative keyword protect budget while preserving opportunity?

                    Return JSON with explanations:
                    {{
                        "negative_keywords": [
                            {{"keyword": "free", "reason": "Budget protection - premium business model"}},
                            {{"keyword": "jobs", "reason": "Intent filter - not recruitment business"}}
                        ]
                    }}"""

            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content.strip()

            try:
                response_data = json.loads(raw)
                negatives = response_data.get("negative_keywords", [])
            except Exception as e:
                logger.error(f"Negative keyword JSON parsing failed: {e}")
                # Enhanced fallback negatives
                fallback_negatives = [
                    {"keyword": "free", "reason": "Universal budget protection"},
                    {"keyword": "cheap", "reason": "Universal budget protection"},
                    {"keyword": "jobs", "reason": "Universal intent filter - employment"},
                    {"keyword": "career", "reason": "Universal intent filter - employment"},
                    {"keyword": "hiring", "reason": "Universal intent filter - employment"},
                    {"keyword": "salary", "reason": "Universal intent filter - employment"},
                    {"keyword": "tutorial", "reason": "Universal informational filter"},
                    {"keyword": "how to", "reason": "Universal informational filter"},
                    {"keyword": "guide", "reason": "Universal informational filter"},
                    {"keyword": "pdf", "reason": "Universal informational filter"},
                    {"keyword": "download", "reason": "Universal informational filter"},
                    {"keyword": "wiki", "reason": "Universal informational filter"},
                    {"keyword": "youtube", "reason": "Universal platform filter"},
                    {"keyword": "video", "reason": "Universal media filter"},
                    {"keyword": "images", "reason": "Universal media filter"},
                    {"keyword": "used", "reason": "Universal condition filter"},
                    {"keyword": "second hand", "reason": "Universal condition filter"},
                    {"keyword": "refurbished", "reason": "Universal condition filter"},
                    {"keyword": "broken", "reason": "Universal condition filter"},
                    {"keyword": "repair", "reason": "Universal service type filter"},
                ]
                negatives = fallback_negatives

            # Enhanced validation and cleaning
            cleaned_negatives = []
            seen = set()
            positive_tokens = set()
            
            # Extract tokens from positive keywords for overlap checking
            for pos in positive_terms:
                positive_tokens.update(re.findall(r"\w+", pos.lower()))

            for item in negatives:
                if not isinstance(item, dict):
                    continue

                kw = _normalize_kw(item.get("keyword", ""))
                reason = item.get("reason", "Budget protection")

                # Basic validation
                if not kw or len(kw) < 2 or len(kw) > 50 or kw in seen:
                    continue

                # Safety pattern checks
                if any(pattern.search(kw) for pattern in self.safety_patterns):
                    continue

                # Don't block exact positive keywords
                if kw in [p.lower() for p in positive_terms]:
                    logger.debug(f"Skipped negative '{kw}' - conflicts with positive keyword")
                    continue

                # Check for high token overlap with positive keywords
                kw_tokens = set(re.findall(r"\w+", kw.lower()))
                overlap_ratio = len(kw_tokens & positive_tokens) / max(len(kw_tokens), 1)

                if overlap_ratio >= 0.8:  # Increased threshold for better precision
                    logger.debug(f"Skipped negative '{kw}' - high overlap with positive keywords")
                    continue

                seen.add(kw)
                cleaned_negatives.append({"keyword": kw, "reason": reason})

                if len(cleaned_negatives) >= 40:
                    break

            logger.info(f"Generated {len(cleaned_negatives)} validated negative keywords")
            return cleaned_negatives

        except Exception as e:
            logger.error(f"Negative keyword generation failed: {e}")
            return []

    def run_improved_pipeline(
        self,
        scraped_data: str,
        customer_id: str,
        access_token:str,
        location_ids: List[str],
        url: str = None,
        language_id: int = 1000,
        seed_count: int = 40,
        target_positive_count: int = 30
    ) -> Dict[str, Any]:
        """
        Executing the complete pipeline
        """
        start_time = time.time()
        logger.info("Starting strategic keyword research pipeline")

        try:
            # STEP 1: Extract business foundation
            logger.info("STEP 1: Extracting business information and USPs")
            brand_info = self.extract_brand_info_from_content(scraped_data, url)
            unique_features = self.extract_unique_features(scraped_data)
            
            # STEP 2: Generate strategic seeds (brand + services + locations)
            logger.info("STEP 2: Generating strategic seed keywords")
            seed_keywords = self.generate_strategic_seeds(
                scraped_data, url, brand_info, unique_features, seed_count
            )
            
            if not seed_keywords:
                logger.error("No seed keywords generated")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 3: Get Google Ads suggestions
            logger.info("STEP 3: Getting Google Ads suggestions for %d strategic seeds", len(seed_keywords))
            all_suggestions = self.get_google_ads_suggestions(
                customer_id=customer_id,
                seed_keywords=seed_keywords,
                access_token = access_token,
                url=url,
                location_id=location_ids,
                language_id=language_id,
                brand_info=brand_info
            )

            # Inject seed keywords back to prevent loss
            suggestion_texts = {s['keyword'] for s in all_suggestions}
            for seed in seed_keywords:
                if seed not in suggestion_texts:
                    all_suggestions.append({
                        "keyword": seed,
                        "volume": 0,
                        "competition": "UNKNOWN",
                        "competitionIndex": 0.0,
                    })

            if not all_suggestions:
                logger.error("No suggestions from Google Ads API")
                return {"positive_keywords": [], "negative_keywords": []}

            # STEP 5: Final optimization for intent and match types
            logger.info("STEP 5: Final optimization for buying intent and match types")
            optimized_positive = self.optimize_for_intent_and_match_types(
                all_suggestions, brand_info, unique_features, scraped_data,url, target_positive_count
            )

            if not optimized_positive:
                logger.error("No keywords survived optimization - using all suggestions fallback")
                optimized_positive = all_suggestions[:target_positive_count]
                for kw in optimized_positive:
                    kw["match_type"] = "phrase"
                    kw["rationale"] = "Fallback selection"

            # STEP 6: Generate negative keywords
            logger.info("STEP 6: Generating negative keywords")
            negative_keywords = self.generate_negative_keywords_llm(
                optimized_positive, scraped_data, url
            )

            result = {
                "positive_keywords": optimized_positive,
                "negative_keywords": negative_keywords,
                "brand_info": brand_info,
                "unique_features": unique_features
            }

            total_time = time.time() - start_time
            logger.info("IMPROVED pipeline completed in %.2f seconds: %d positive, %d negative keywords",
                        total_time, len(optimized_positive), len(negative_keywords))

            return result

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return {"positive_keywords": [], "negative_keywords": []}
        

