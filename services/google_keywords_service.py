import os
import logging
import time
import requests
import json
import re

from typing import List, Dict, Set, Any
from utils.text_utils import normalize_text, safe_truncate_to_sentence, get_safety_patterns, setup_apis, get_fallback_negative_keywords
from utils.prompt_loader import load_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




class GoogleKeywordService:

    def __init__(self):
        self.openai_client = setup_apis()
        self.safety_patterns = get_safety_patterns()

    def extract_business_metadata(self, scraped_data: str, url: str = None) -> Dict[str, Any]:
        try:

            content_summary = safe_truncate_to_sentence(str(scraped_data), 2000)

            prompt_template = load_prompt('business_metadata_prompt.txt')
            prompt = prompt_template.format(url=url or 'Not provided', content_summary=content_summary)

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            raw = resp.choices[0].message.content.strip()
            brand_info = json.loads(raw)

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

    def extract_business_unique_features(self, scraped_data: str) -> List[str]:

        usp_prompt_template = load_prompt('business_usp_prompt.txt')
        usp_prompt = usp_prompt_template.format(scraped_data = scraped_data)

        try:
            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": usp_prompt}],
                max_tokens=400,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            usp_data = json.loads(resp.choices[0].message.content.strip())
            unique_features = [str(f).lower().strip() for f in usp_data.get("features", []) 
                                if isinstance(f, str) and len(str(f).strip()) > 0]
            
            logger.info(f"Extracted USPs: {unique_features}")
        except Exception as e:
            logger.warning(f"USP extraction failed: {e}")
            unique_features = []
        return unique_features

    def generate_seed_keywords(self, scraped_data: str, url: str = None, brand_info: Dict[str, Any] = None, unique_features: List[str] = None, max_kw: int = 40) -> List[str]:
        try:
            content_summary = safe_truncate_to_sentence(str(scraped_data), 2000)
            
            brand_name = brand_info.get("brand_name", "Unknown")
            primary_location = brand_info.get("primary_location", "Unknown")
            service_areas = brand_info.get("service_areas", [])
            business_type = brand_info.get("business_type", "Unknown")

            location_context = ""
            if primary_location != "Unknown":
                location_context += f"Primary Location: {primary_location}\n"
            if service_areas:
                location_context += f"Service Areas: {', '.join(service_areas)}\n"

            features_context = ""
            if unique_features:
                features_context = f"Unique Features: {', '.join(unique_features)}\n"

            seed_prompt_template = load_prompt('seed_keywords_prompt.txt')
            prompt = seed_prompt_template.format(
                url=url or 'Not provided',
                content_summary=content_summary,
                brand_name=brand_name,
                business_type=business_type,
                location_context=location_context,
                features_context=features_context,
                max_kw=max_kw,
                primary_location=primary_location,
                service_areas=service_areas,
                unique_features=unique_features
                )

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content.strip()

            parsed = []
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("Response not a list")
            except Exception:

                parts = re.findall(r'"([^"]+)"', raw)
                if not parts:
                    parts = re.split(r'[\n,•;]+', raw)
                parsed = [p.strip().strip('"\'') for p in parts if p.strip()]

            normalized = []
            seen = set()
            for kw in parsed:
                if not isinstance(kw, str):
                    continue
                k = normalize_text(kw)
                if 2 <= len(k) and k not in seen:
                    normalized.append(k)
                    seen.add(k)
            logger.info(f"Generated {len(normalized)} strategic seed keywords")
            return normalized[:max_kw]

        except Exception as e:
            logger.exception("Strategic seed generation failed: %s", e)
            return []

    def fetch_google_ads_suggestions(
        self,
        customer_id: str,
        seed_keywords: List[str],
        access_token: str,
        url: str = None,
        location_ids :List[str] = None,
        language_id: int = 1000,
        chunk_size: int = 15,
    ) -> List[Dict[str, Any]]:
        
        try:
            if location_ids is None or len(location_ids) == 0:
                location_ids = ["geoTargetConstants/2840"]  # India
            
            all_suggestions: List[Dict[str, Any]] = []
            seen_keywords: Set[str] = set()

            # Google Ads API endpoint
            developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
            login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID")

            if not developer_token:
                raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")
            
            endpoint = f"https://googleads.googleapis.com/v20/customers/{customer_id}:generateKeywordIdeas"

            # Headers for API call
            headers = {
                "authorization": f"Bearer {access_token}",
                "developer-token": developer_token,
                "content-type": "application/json",
                "login-customer-id":login_customer_id # without this i was getting permission denied
            }

            logger.info(f"Targeting {len(location_ids)} locations: {location_ids}")

            # Process in chunks
            total_chunks = (len(seed_keywords) + chunk_size - 1) // chunk_size

            for i in range(0, len(seed_keywords), chunk_size):
                chunk = seed_keywords[i: i + chunk_size]
                chunk_num = i // chunk_size + 1

                logger.info("Processing chunk %d/%d (size=%d)", chunk_num, total_chunks, len(chunk))

                try:
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

                    response_data = response.json()
                    results = response_data.get("results", [])
                    
                    if not results:
                        logger.info(f"No results in chunk {chunk_num}")
                        continue

                    chunk_suggestions = []
                    for kw_idea in results:
                        try:
                            text_val = kw_idea.get("text", "")
                            if not text_val:
                                continue

                            text_norm = normalize_text(text_val)
                            if text_norm in seen_keywords or len(text_norm) < 2 or len(text_norm.split()) > 6:
                                continue

                            metrics = kw_idea.get("keywordIdeaMetrics", {})

                            try:
                                volume = int(metrics.get("avgMonthlySearches", 0))
                            except (ValueError, TypeError):
                                volume = 0
                            
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

                    if i + chunk_size < len(seed_keywords):
                        time.sleep(0.5)

                except Exception as e:
                    logger.exception("Failed chunk %d: %s", chunk_num, str(e)[:100])
                    continue

            final_suggestions = []
            seen_final = set()
            all_suggestions.sort(key=lambda x: x["volume"], reverse=True)

            for suggestion in all_suggestions:
                kw = suggestion["keyword"]
                if kw not in seen_final:
                    final_suggestions.append(suggestion)
                    seen_final.add(kw)

            logger.info("TOTAL: %d suggestions from Google Ads API for %d locations", len(final_suggestions), len(location_ids))
            return final_suggestions

        except Exception as e:
            logger.exception("Google Ads suggestions failed: %s", e)
            return []

    def select_positive_keywords(
        self,
        all_suggestions: List[Dict[str, Any]],
        business_info: Dict[str, Any],
        unique_features: List[str],
        scraped_data: str,
        url: str = None,
        target_count: int = 30
    ) -> List[Dict[str, Any]]:

        try:
            keyword_data = []
            for s in all_suggestions:
                kw = s.get("keyword", "")
                vol = s.get("volume", 0)
                comp =s.get("competitionIndex",0.0)
                roi = vol / (1 + s.get("competitionIndex", 0.0))
                
                keyword_data.append(f"{kw} | Volume:{vol} | ROI:{roi:.0f} | Competition: {comp:.2f} ")
            
            keywords_text = "\n".join(keyword_data)
            business_summary = safe_truncate_to_sentence(str(scraped_data), 2500)


            prompt_template = load_prompt('positive_keywords_prompt.txt')
            prompt = prompt_template.format(
                business_summary=business_summary,
                keywords_text=keywords_text,
                target_count=target_count,
                url=url or 'Not provided',
                unique_features=unique_features,
                brand_name = business_info.get("brand_name", "Unknown"),
                business_type = business_info.get("business_type", "Unknown"),
                primary_location = business_info.get("primary_location", "Unknown"),
                service_areas = ", ".join(business_info.get("service_areas", [])) or "Not provided",
                brand_keywords = ", ".join(business_info.get("brand_keywords", [])) or "Not provided"
            )

            resp = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content.strip()
            response_data = json.loads(raw)
            optimized_list = response_data.get("keywords", [])
            
            suggestion_map = {s["keyword"]: s for s in all_suggestions}
            final_optimized = []
            seen = set()
            
            for item in optimized_list:
                kw = normalize_text(item.get("keyword", ""))
                if kw in suggestion_map and kw not in seen:
                    final_optimized.append({
                        **suggestion_map[kw],
                        "match_type": item.get("match_type", "phrase"),
                        "rationale": item.get("rationale", "AI selected")
                    })
                    seen.add(kw)
            
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
            logger.exception("Final optimization failed: %s", e)
            fallback = []
            for i, s in enumerate(all_suggestions[:target_count]):
                match_type = "exact" if i < target_count * 0.3 else ("phrase" if i < target_count * 0.6 else "broad")
                fallback.append({
                    **s,
                    "match_type": match_type,
                    "rationale": "Fallback selection"
                })
            return fallback

    def generate_negative_keywords(self, optimized_positive_keywords: List[Dict[str, Any]], scraped_data: str, url: str = None) -> List[Dict[str, Any]]:

        try:
            business_summary = safe_truncate_to_sentence(str(scraped_data), 2500)
            positive_terms = [kw.get("keyword", "") for kw in optimized_positive_keywords]
            positive_text = ", ".join(positive_terms)

            prompt_template = load_prompt('negative_keywords_prompt.txt')
            prompt = prompt_template.format(
                business_summary=business_summary,
                positive_text=positive_text,
                url=url or 'Not provided'
            )

            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content.strip()

            try:
                response_data = json.loads(raw)
                negatives = response_data.get("negative_keywords", [])
            except Exception as e:
                logger.error(f"Negative keyword JSON parsing failed: {e}")
                negatives = get_fallback_negative_keywords()

            cleaned_negatives = []
            seen = set()
            positive_tokens = set()
            
            for pos in positive_terms:
                positive_tokens.update(re.findall(r"\w+", pos.lower()))

            for item in negatives:
                if not isinstance(item, dict):
                    continue

                kw = normalize_text(item.get("keyword", ""))
                reason = item.get("reason", "Budget protection")

                if not kw or len(kw) < 2 or len(kw) > 50 or kw in seen:
                    continue

                if any(pattern.search(kw) for pattern in self.safety_patterns):
                    continue

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

    def extract_positive_strategy(
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

        start_time = time.time()
        logger.info("Starting strategic keyword research pipeline")

        try:
            # STEP 1: Extract business foundation
            logger.info("STEP 1: Extracting business information and USPs")
            brand_info = self.extract_business_metadata(scraped_data, url)
            unique_features = self.extract_business_unique_features(scraped_data)
            
            # STEP 2: Generate strategic seeds (brand + services + locations)
            logger.info("STEP 2: Generating strategic seed keywords")
            seed_keywords = self.generate_seed_keywords(
                scraped_data, url, brand_info, unique_features, seed_count
            )
            
            if not seed_keywords:
                logger.error("No seed keywords generated")
                return {"positive_keywords": []}

            # STEP 3: Get Google Ads suggestions
            logger.info("STEP 3: Getting Google Ads suggestions for %d strategic seeds", len(seed_keywords))
            all_suggestions = self.fetch_google_ads_suggestions(
                customer_id=customer_id,
                seed_keywords=seed_keywords,
                access_token = access_token,
                url=url,
                location_ids=location_ids,
                language_id=language_id,
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
                return {"positive_keywords": []}

            # STEP 4: Final optimization for intent and match types
            logger.info("STEP 4: Final optimization for buying intent and match types")
            optimized_positive = self.select_positive_keywords(
                all_suggestions, brand_info, unique_features, scraped_data,url, target_positive_count
            )

            if not optimized_positive:
                logger.error("No keywords survived optimization - using all suggestions fallback")
                optimized_positive = all_suggestions[:target_positive_count]
                for kw in optimized_positive:
                    kw["match_type"] = "phrase"
                    kw["rationale"] = "Fallback selection"

            result = {
                "positive_keywords": optimized_positive,
                "brand_info": brand_info,
                "unique_features": unique_features
            }

            total_time = time.time() - start_time
            logger.info("Positive pipeline completed in %.2f seconds: %d positive keywords",
                        total_time, len(optimized_positive))

            return result

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return {"positive_keywords": []}

