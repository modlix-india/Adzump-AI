import os, logging, time, asyncio, json
import httpx
from typing import List
from oserver.services.connection import fetch_google_api_token_simple
from utils import text_utils, prompt_loader
from services.openai_client import chat_completion
from utils.keyword_utils import KeywordUtils
from services.session_manager import sessions
from fastapi import HTTPException
from services.business_service import BusinessService
from models.business_model import BusinessMetadata

# Import Pydantic models
from models.keyword_model import (
    KeywordSuggestion,
    OptimizedKeyword,
    NegativeKeyword,
    KeywordResearchRequest,
    KeywordResearchResult,
    KeywordSelectionResponse,
    GoogleNegativeKwReq,
    NegativeKeywordResponse,
    MatchType,
    KeywordType,
    CompetitionLevel,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GoogleKeywordService:
    OPENAI_MODEL = "gpt-4o-mini"
    DEFAULT_LOCATION_IDS = ["geoTargetConstants/2356"]  # India
    MIN_KEYWORD_LENGTH = 2
    MAX_KEYWORD_WORDS = 6
    DEFAULT_SEED_COUNT = 80
    TARGET_POSITIVE_COUNT = 30
    FINAL_KEYWORD_LIMIT = 15
    DEFAULT_LANGUAGE_ID = 1000
    HTTP_TIMEOUT = 30.0
    CHUNK_SIZE = 15
    RETRY_ATTEMPTS = 2
    RETRY_DELAY = 1.0
    CHUNK_DELAY = 0.5

    SEED_PROMPT_MAP = {
        KeywordType.BRAND: "seed_keywords_brand_prompt.txt",
        KeywordType.GENERIC: "seed_keywords_generic_prompt.txt",
    }

    POSITIVE_PROMPT_MAP = {
        KeywordType.BRAND: "positive_keywords_brand_prompt.txt",
        KeywordType.GENERIC: "positive_keywords_generic_prompt.txt",
    }

    def __init__(self):
        self.safety_patterns = text_utils.get_safety_patterns()
        self.business_extractor = BusinessService()

    async def generate_seed_keywords(
        self,
        scraped_data: str,
        url: str = None,
        brand_info: BusinessMetadata = None,
        unique_features: List[str] = None,
        max_kw: int = DEFAULT_SEED_COUNT,
        keyword_type: KeywordType = KeywordType.GENERIC,
    ) -> List[str]:
        prompt_file = GoogleKeywordService._get_prompt_file(
            self.SEED_PROMPT_MAP, keyword_type
        )
        prompt = prompt_loader.format_prompt(
            prompt_file,
            scraped_data=scraped_data,
            url=url,
            brand_info=brand_info,
            unique_features=unique_features,
            max_kw=max_kw,
        )

        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=800,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content.strip()

            seed_keywords = KeywordUtils.parse_and_normalize_seed_keywords(raw, max_kw)

            logger.info(
                f"Generated {len(seed_keywords)} strategic seed keywords for type '{keyword_type.value}'"
            )
            logger.info("seed keywords generated: " + str(seed_keywords))
            return seed_keywords

        except Exception as e:
            logger.exception("Strategic seed generation failed: %s", e)
            return []

    async def fetch_google_ads_suggestions(
        self,
        customer_id: str,
        login_customer_id: str,
        client_code: str,
        seed_keywords: List[str],
        url: str = None,
        location_ids: List[str] = None,
        language_id: int = DEFAULT_LANGUAGE_ID,
        chunk_size: int = CHUNK_SIZE,
    ) -> List[KeywordSuggestion]:
        access_token = fetch_google_api_token_simple(client_code)

        location_ids = location_ids or self.DEFAULT_LOCATION_IDS  # India
        all_suggestions: List[KeywordSuggestion] = []

        competition_map = {
            "LOW": CompetitionLevel.LOW,
            "MEDIUM": CompetitionLevel.MEDIUM,
            "HIGH": CompetitionLevel.HIGH,
        }

        try:
            developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
            if not developer_token:
                raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")

            endpoint = f"https://googleads.googleapis.com/v20/customers/{customer_id}:generateKeywordIdeas"
            headers = {
                "authorization": f"Bearer {access_token}",
                "developer-token": developer_token,
                "content-type": "application/json",
                "login-customer-id": login_customer_id,
            }

            async with httpx.AsyncClient(timeout=self.HTTP_TIMEOUT) as client:
                for i in range(0, len(seed_keywords), chunk_size):
                    chunk = seed_keywords[i : i + chunk_size]
                    chunk_num = i // chunk_size + 1
                    logger.info("Processing chunk %d (size=%d)", chunk_num, len(chunk))

                    try:
                        payload = {
                            "language": f"languageConstants/{language_id}",
                            "geoTargetConstants": [
                                f"{loc_id}" for loc_id in location_ids
                            ],
                            "includeAdultKeywords": False,
                            "keywordPlanNetwork": "GOOGLE_SEARCH_AND_PARTNERS",
                        }
                        if url and url.strip():
                            payload["keywordAndUrlSeed"] = {
                                "keywords": chunk,
                                "url": str(url).strip(),
                            }
                        else:
                            payload["keywordSeed"] = {"keywords": chunk}

                        response = None
                        for attempt in range(self.RETRY_ATTEMPTS):
                            try:
                                response = await client.post(
                                    endpoint, headers=headers, json=payload
                                )
                                if response.status_code == 200:
                                    break
                                logger.warning(
                                    f"API error attempt {attempt + 1}: {response.status_code}"
                                )
                                await asyncio.sleep(self.RETRY_DELAY)
                            except httpx.RequestError as ex:
                                logger.warning(
                                    f"Request error attempt {attempt + 1}: {str(ex)[:100]}"
                                )
                                await asyncio.sleep(self.RETRY_DELAY)

                        if not response or response.status_code != 200:
                            logger.warning(
                                f"Skipping chunk {chunk_num} due to invalid response"
                            )
                            continue

                        results = response.json().get("results", [])
                        if not results:
                            logger.info(f"No results in chunk {chunk_num}")
                            continue

                        for kw_idea in results:
                            try:
                                text_val = kw_idea.get("text", "")
                                if not text_val:
                                    continue

                                text_norm = text_utils.normalize_text(text_val)
                                if (
                                    len(text_norm) < self.MIN_KEYWORD_LENGTH
                                    or len(text_norm.split()) > self.MAX_KEYWORD_WORDS
                                ):
                                    continue

                                metrics = kw_idea.get("keywordIdeaMetrics", {})
                                raw_competition = metrics.get("competition", "UNKNOWN")

                                # Check for existing keyword
                                existing_idx = next(
                                    (
                                        idx
                                        for idx, s in enumerate(all_suggestions)
                                        if s.keyword == text_norm
                                    ),
                                    None,
                                )

                                new_volume = int(
                                    metrics.get("avgMonthlySearches", 0) or 0
                                )

                                if existing_idx is not None:
                                    # Replace if new volume is higher
                                    if (
                                        new_volume
                                        > all_suggestions[existing_idx].volume
                                    ):
                                        all_suggestions[existing_idx] = (
                                            KeywordSuggestion(
                                                keyword=text_norm,
                                                volume=new_volume,
                                                competition=competition_map.get(
                                                    raw_competition,
                                                    CompetitionLevel.UNKNOWN,
                                                ),
                                                competitionIndex=float(
                                                    metrics.get("competitionIndex", 0)
                                                    or 0
                                                )
                                                / 100.0,
                                            )
                                        )
                                else:
                                    # New keyword
                                    suggestion = KeywordSuggestion(
                                        keyword=text_norm,
                                        volume=new_volume,
                                        competition=competition_map.get(
                                            raw_competition, CompetitionLevel.UNKNOWN
                                        ),
                                        competitionIndex=float(
                                            metrics.get("competitionIndex", 0) or 0
                                        )
                                        / 100.0,
                                    )
                                    all_suggestions.append(suggestion)

                            except (ValueError, TypeError) as e:
                                logger.warning(
                                    f"Validation error for {text_norm}:{str(e)[:50]}"
                                )

                            except Exception as e:
                                logger.debug(
                                    "Error processing keyword: %s", str(e)[:50]
                                )
                                continue

                        await asyncio.sleep(self.CHUNK_DELAY)

                    except Exception as e:
                        logger.exception("Failed chunk %d: %s", chunk_num, str(e)[:100])
                        continue

            all_suggestions.sort(key=lambda x: x.volume, reverse=True)
            logger.info(
                "TOTAL: %d suggestions from Google Ads API for %d locations",
                len(all_suggestions),
                len(location_ids),
            )
            logger.info("all suggestion from google ads api : %s", all_suggestions)
            return all_suggestions

        except Exception as e:
            logger.exception("Google Ads suggestions failed: %s", e)
            return []

    async def select_positive_keywords(
        self,
        all_suggestions: List[KeywordSuggestion],
        business_info: BusinessMetadata,
        unique_features: List[str],
        scraped_data: str,
        keyword_type: KeywordType,
        url: str = None,
        target_count: int = TARGET_POSITIVE_COUNT,
    ) -> List[OptimizedKeyword]:
        prompt_file = GoogleKeywordService._get_prompt_file(
            self.POSITIVE_PROMPT_MAP, keyword_type
        )

        prompt = prompt_loader.format_prompt(
            prompt_file,
            scraped_data=scraped_data,
            url=url,
            brand_info=business_info,
            unique_features=unique_features,
            target_count=target_count,
            suggestions=all_suggestions,
        )

        resp = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=self.OPENAI_MODEL,
            max_tokens=3000,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        raw = resp.choices[0].message.content.strip()
        response_data = KeywordSelectionResponse(**json.loads(raw))

        suggestion_map = {s.keyword: s for s in all_suggestions}
        final_optimized: List[OptimizedKeyword] = []
        seen = set()

        for item in response_data.keywords:
            kw_text = text_utils.normalize_text(item.get("keyword", ""))
            if kw_text in suggestion_map and kw_text not in seen:
                base_suggestion = suggestion_map[kw_text]

                match_type_str = item.get("match_type", "phrase")
                try:
                    match_type = MatchType(match_type_str.lower())
                except ValueError:
                    match_type = MatchType.PHRASE

                optimized = OptimizedKeyword(
                    keyword=base_suggestion.keyword,
                    volume=base_suggestion.volume,
                    competition=base_suggestion.competition,
                    competitionIndex=base_suggestion.competitionIndex,
                    match_type=match_type,
                    rationale=item.get("rationale", "AI selected"),
                    is_cross_business=item.get("is_cross_business", False),
                )

                final_optimized.append(optimized)
                seen.add(kw_text)

        # Filter out zero volume keywords and sort by volume descending
        filtered_optimized = [kw for kw in final_optimized if kw.volume > 0]
        filtered_optimized.sort(key=lambda x: x.volume, reverse=True)

        logger.info(
            f"Final optimization: {len(filtered_optimized)} keywords selected (non-zero volume)"
        )
        logger.info(f"Final optimized keywords: {filtered_optimized}")

        return filtered_optimized[: self.FINAL_KEYWORD_LIMIT]

    async def generate_negative_keywords(
        self,
        optimized_positive_keywords: List[OptimizedKeyword],
        scraped_data: str,
        url: str = None,
    ) -> List[NegativeKeyword]:
        try:
            logger.info(
                f"Generating negative keywords for {len(optimized_positive_keywords)} positive keywords"
            )
            prompt = prompt_loader.format_prompt(
                "negative_keywords_prompt.txt",
                scraped_data=scraped_data,
                url=url,
                positive_keywords=optimized_positive_keywords,
            )

            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=1500,
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            try:
                raw = response.choices[0].message.content.strip()
                response_data = NegativeKeywordResponse(**json.loads(raw))
                negatives_raw = response_data.negative_keywords
            except Exception as e:
                logger.error(
                    f"Negative keyword JSON parsing failed: {e}, using fallback"
                )
                negatives_raw = text_utils.get_fallback_negative_keywords()

            cleaned_negatives = KeywordUtils.filter_and_validate_negatives(
                negatives_raw, optimized_positive_keywords, self.safety_patterns
            )

            logger.info(
                f"Generated {len(cleaned_negatives)} validated negative keywords"
            )
            logger.info(f"Final negative keywords: {cleaned_negatives}")
            return cleaned_negatives

        except Exception as e:
            logger.error(f"Negative keyword generation failed: {e}")
            return []

    async def extract_positive_strategy(
        self,
        keyword_request: KeywordResearchRequest,
        client_code: str,
        session_id: str,
        access_token: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
    ) -> KeywordResearchResult:
        location_ids = keyword_request.location_ids or self.DEFAULT_LOCATION_IDS
        language_id = keyword_request.language_id or self.DEFAULT_LANGUAGE_ID
        seed_count = keyword_request.seed_count or self.DEFAULT_SEED_COUNT
        keyword_type = keyword_request.keyword_type or KeywordType.GENERIC
        target_positive_count = (
            keyword_request.target_positive_count or self.TARGET_POSITIVE_COUNT
        )

        start_time = time.time()
        logger.info("Starting strategic keyword research pipeline")

        # validate the session
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Invalid or expired session.")

        session = sessions[session_id]
        login_customer_id = session.get("campaign_data", {}).get("loginCustomerId")
        customer_id = session.get("campaign_data", {}).get("customerId")

        if not login_customer_id and not customer_id:
            raise HTTPException(
                status_code=401, detail="loginCustomerId and customerId not found in session."
            )

        # get business details
        business_data = await self.business_extractor.fetch_product_details(
            data_object_id=keyword_request.data_object_id,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        scraped_data = business_data.get("finalSummary", "")
        url = business_data.get("businessUrl", "")

        # validate we got data
        if not scraped_data:
            logger.error(
                f"No scraped data found for data_object_id: {keyword_request.data_object_id}"
            )
            return KeywordResearchResult(
                positive_keywords=[], brand_info=BusinessMetadata(), unique_features=[]
            )

        brand_info = BusinessMetadata()
        unique_features = []
        seed_keywords = []

        try:
            logger.info("STEP 1: Extracting business information and USPs")
            brand_info, unique_features = await asyncio.gather(
                self.business_extractor.extract_business_metadata(scraped_data, url),
                self.business_extractor.extract_business_unique_features(scraped_data),
                return_exceptions=True,
            )

            # Handle exceptions from parallel execution
            if isinstance(brand_info, Exception):
                logger.warning(f"Brand extraction failed, using defaults: {brand_info}")
                brand_info = BusinessMetadata()
            if isinstance(unique_features, Exception):
                logger.warning(f"USP extraction failed: {unique_features}")
                unique_features = []

            logger.info("STEP 2: Generating strategic seed keywords")
            seed_keywords = await self.generate_seed_keywords(
                scraped_data, url, brand_info, unique_features, seed_count, keyword_type
            )

            if not seed_keywords:
                logger.error("No seed keywords generated - returning empty results")
                return KeywordResearchResult(
                    positive_keywords=[],
                    brand_info=brand_info,
                    unique_features=unique_features,
                )
            logger.info(
                f"Generated {len(seed_keywords)} seed keywords for type '{keyword_type.value}"
            )

            logger.info(
                "STEP 3: Getting Google Ads suggestions for %d strategic seeds",
                len(seed_keywords),
            )
            all_suggestions = await self.fetch_google_ads_suggestions(
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                client_code=client_code,
                seed_keywords=seed_keywords,
                url=url,
                location_ids=location_ids,
                language_id=language_id,
            )

            if not all_suggestions:
                logger.error("No suggestions from Google Ads API - creating from seed")
                all_suggestions = [
                    KeywordSuggestion(
                        keyword=seed,
                        volume=10,  # added small but not zero
                        competition=CompetitionLevel.LOW,  # low competition
                        competitionIndex=0.1,  # Low competition index
                    )
                    for seed in seed_keywords[: target_positive_count * 2]
                ]
            else:
                # Inject seed keywords back to prevent loss
                suggestion_texts = {s.keyword for s in all_suggestions}
                for seed in seed_keywords:
                    if seed not in suggestion_texts:
                        all_suggestions.append(
                            KeywordSuggestion(
                                keyword=seed,
                                volume=10,  # added small but not zero
                                competition=CompetitionLevel.LOW,  # low competition
                                competitionIndex=0.1,  # low competition index
                            )
                        )

            logger.info("STEP 4: Final optimization for buying intent and match types")
            optimized_positive = await self.select_positive_keywords(
                all_suggestions,
                brand_info,
                unique_features,
                scraped_data,
                keyword_type,
                url,
                target_positive_count,
            )

            result = KeywordResearchResult(
                positive_keywords=optimized_positive,
                brand_info=brand_info,
                unique_features=unique_features,
            )

            total_time = time.time() - start_time
            logger.info(
                "Positive pipeline completed in %.2f seconds: %d positive keywords",
                total_time,
                result.total_keywords,
            )
            logger.info(f"Match type percentages: {result.get_match_type_percentage()}")
            logger.info(f"Cross-business terms: {result.cross_business_count}")

            return result

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            return KeywordResearchResult(
                positive_keywords=[],
                brand_info=brand_info,
                unique_features=unique_features,
            )

    async def extract_negative_strategy(
        self,
        keyword_request: GoogleNegativeKwReq,
        client_code: str,
        access_token: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
    ) -> List[NegativeKeyword]:
        data_object_id = keyword_request.data_object_id
        positive_keywords = keyword_request.positive_keywords

        try:
            # Fetch business details
            business_data = await self.business_extractor.fetch_product_details(
                data_object_id=data_object_id,
                access_token=access_token,
                client_code=client_code,
                x_forwarded_host=x_forwarded_host,
                x_forwarded_port=x_forwarded_port,
            )
            scraped_data = business_data.get("finalSummary", "")
            url = business_data.get("businessUrl", "")

            # Validate we got data
            if not scraped_data:
                logger.warning(
                    f"No scraped data found for data_object_id: {data_object_id}"
                )
                return []

            logger.info("Started negative keyword generation")

            # Generate negative keywords
            negatives = await self.generate_negative_keywords(
                optimized_positive_keywords=positive_keywords,
                scraped_data=scraped_data,
                url=url,
            )

            logger.info(f"Generated {len(negatives)} negative keywords")
            return negatives

        except Exception as e:
            logger.exception(f"Negative keyword generation failed: {e}")
            return []

    @staticmethod
    def _get_prompt_file(prompt_map: dict, keyword_type: KeywordType) -> str:
        return prompt_map.get(keyword_type, prompt_map[KeywordType.GENERIC])
