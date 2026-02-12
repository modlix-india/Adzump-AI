import os
import asyncio
from typing import List, Dict, Optional, Any
from third_party.google.google_utils import google_ads_utils
from utils import google_dateutils as date_utils
from structlog import get_logger  # type: ignore
from utils import text_utils
from third_party.google.models.keyword_model import (
    KeywordSuggestion,
    CompetitionLevel,
    Keyword,
    FetchKeywordsResponse,
)
from exceptions.custom_exceptions import GoogleAdsException

logger = get_logger(__name__)

# Constants
DEFAULT_LOCATION_IDS = ["geoTargetConstants/2356"]  # India
DEFAULT_LANGUAGE_ID = 1000  # English
MIN_KEYWORD_LENGTH = 2
MAX_KEYWORD_WORDS = 6
CHUNK_SIZE = 15
RETRY_ATTEMPTS = 3
CHUNK_DELAY = 0.5

COMPETITION_MAP = {
    "LOW": CompetitionLevel.LOW,
    "MEDIUM": CompetitionLevel.MEDIUM,
    "HIGH": CompetitionLevel.HIGH,
    "UNKNOWN": CompetitionLevel.UNKNOWN,
}


# Fetch the existing campaign keywords
async def fetch_campaign_keywords(
    customer_id: str,
    campaign_id: str,
    access_token: str,
    login_customer_id: str,
    developer_token: Optional[str] = None,
    duration: Optional[str] = None,
    ad_group_id: Optional[str] = None,
    include_negatives: bool = False,
    include_metrics: bool = False,
) -> FetchKeywordsResponse:
    developer_token = developer_token or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not developer_token:
        raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")

    duration = duration or "LAST_30_DAYS"
    logger.info(
        "Fetching keywords for campaign",
        campaign_id=campaign_id,
        duration=duration,
    )

    query = _build_keywords_fetch_query(
        campaign_id=campaign_id,
        ad_group_id=ad_group_id,
        duration=duration,
        include_negatives=include_negatives,
        include_metrics=include_metrics,
    )

    try:
        results = await google_ads_utils.execute_google_ads_query(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=access_token,
            developer_token=developer_token,
            query=query.strip(),
            retry_attempts=RETRY_ATTEMPTS,
            use_stream=True,
        )

        if not results:
            logger.warning("No keywords found", duration=duration or "LAST_30_DAYS")
            return FetchKeywordsResponse(
                status="no_data",
                keywords=[],
                keywords_by_ad_group={},
                total_keywords=0,
                total_ad_groups=0,
                date_range_used=duration or "LAST_30_DAYS",
            )

        logger.info(f"Query returned {len(results)} keywords")

        keywords = [Keyword.from_google_row(row) for row in results]
        logger.info(f"Successfully parsed {len(keywords)} keywords")

        keywords_by_ad_group = google_ads_utils.group_keywords_by_ad_group(keywords)

        return FetchKeywordsResponse(
            status="success",
            keywords=keywords,
            keywords_by_ad_group=keywords_by_ad_group,
            total_keywords=len(keywords),
            total_ad_groups=len(keywords_by_ad_group),
            date_range_used=duration or "LAST_30_DAYS",
        )

    except Exception as e:
        logger.exception(f"Error fetching keywords: {e}")
        if not isinstance(e, GoogleAdsException):
            raise GoogleAdsException(
                message=f"Error fetching campaign keywords: {str(e)}"
            )
        raise


def _build_keywords_fetch_query(
    campaign_id: str,
    ad_group_id: Optional[str] = None,
    duration: Optional[str] = None,
    include_negatives: bool = False,
    include_metrics: bool = False,
) -> str:
    """Build GAQL query for fetching campaign keywords."""
    date_filter = date_utils.format_date_range(duration)
    negative_filter = (
        "" if include_negatives else "AND ad_group_criterion.negative = FALSE"
    )
    ad_group_filter = f"AND ad_group.id = {ad_group_id}" if ad_group_id else ""
    date_clause = f"AND {date_filter}" if date_filter else ""

    metrics_fields = ""
    if include_metrics:
        metrics_fields = """
            metrics.impressions,
            metrics.clicks,
            metrics.ctr,
            metrics.average_cpc,
            metrics.cost_micros,
            metrics.conversions,
            metrics.cost_per_conversion
        """

    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            ad_group.id,
            ad_group.name,
            ad_group_criterion.criterion_id,
            ad_group_criterion.status,
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.quality_info.quality_score
            {", " + metrics_fields if metrics_fields else ""}
        FROM keyword_view
        WHERE campaign.id = {campaign_id}
            {ad_group_filter}
            {date_clause}
            AND ad_group_criterion.status = 'ENABLED'
            AND ad_group.status = 'ENABLED'
            AND campaign.status = 'ENABLED'
            {negative_filter}
        ORDER BY ad_group.id, ad_group_criterion.criterion_id
    """

    return query.strip()


# Generate keyword ideas from Google Ads API
async def google_ads_generate_keyword_ideas(
    customer_id: str,
    login_customer_id: str,
    access_token: str,
    seed_keywords: List[str],
    developer_token: Optional[str] = None,
    url: str = None,
    location_ids: List[str] = None,
    language_id: int = DEFAULT_LANGUAGE_ID,
    chunk_size: int = CHUNK_SIZE,
) -> List[KeywordSuggestion]:
    """Generate keyword ideas from Google Ads API."""
    location_ids = location_ids or DEFAULT_LOCATION_IDS
    all_suggestions: List[KeywordSuggestion] = []

    try:
        developer_token = developer_token or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        if not developer_token:
            raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")

        # Process each chunk
        for i in range(0, len(seed_keywords), chunk_size):
            chunk = seed_keywords[i : i + chunk_size]
            chunk_num = i // chunk_size + 1

            await _process_keyword_chunk(
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                access_token=access_token,
                developer_token=developer_token,
                chunk=chunk,
                chunk_num=chunk_num,
                url=url,
                location_ids=location_ids,
                language_id=language_id,
                all_suggestions=all_suggestions,
            )
            await asyncio.sleep(CHUNK_DELAY)

        all_suggestions.sort(key=lambda x: x.volume, reverse=True)
        logger.info(f"TOTAL: {len(all_suggestions)} suggestions from Google Ads API")

        return all_suggestions

    except Exception as e:
        logger.exception(f"Google Ads suggestions failed: {e}")
        if not isinstance(e, GoogleAdsException):
            raise GoogleAdsException(
                message=f"Failed to generate keyword ideas: {str(e)}"
            )
        raise


async def _process_keyword_chunk(
    customer_id: str,
    login_customer_id: str,
    access_token: str,
    developer_token: str,
    chunk: List[str],
    chunk_num: int,
    url: Optional[str],
    location_ids: List[str],
    language_id: int,
    all_suggestions: List[KeywordSuggestion],
) -> int:
    """Process a single chunk: fetch from API and merge into all_suggestions."""
    try:
        logger.info(f"Processing chunk {chunk_num} (size={len(chunk)})")

        payload = _build_keyword_ideas_payload(chunk, url, location_ids, language_id)

        response_data = await google_ads_utils.execute_google_ads_service_call(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            access_token=access_token,
            developer_token=developer_token,
            service_method="generateKeywordIdeas",
            payload=payload,
        )

        results = response_data.get("results", [])
        if not results:
            logger.info(f"No results in chunk {chunk_num}")
            return 0

        added_count = _parse_and_merge_suggestions(results, all_suggestions)
        logger.info(f"Chunk {chunk_num}: Added/updated {added_count} suggestions")

        return added_count

    except Exception as e:
        logger.exception(f"Failed chunk {chunk_num}: {str(e)[:100]}")
        return 0


def _build_keyword_ideas_payload(
    chunk: List[str], url: Optional[str], location_ids: List[str], language_id: int
) -> Dict[str, Any]:
    """Build the payload for keyword ideas API request."""
    payload = {
        "language": f"languageConstants/{language_id}",
        "geoTargetConstants": location_ids,
        "includeAdultKeywords": False,
        "keywordPlanNetwork": "GOOGLE_SEARCH_AND_PARTNERS",
    }

    if url and url.strip():
        payload["keywordAndUrlSeed"] = {"keywords": chunk, "url": str(url).strip()}
    else:
        payload["keywordSeed"] = {"keywords": chunk}

    return payload


def _parse_and_merge_suggestions(
    api_results: List[Dict[str, Any]], all_suggestions: List[KeywordSuggestion]
) -> int:
    """Parse API results and merge into all_suggestions list."""
    added_count = 0
    existing_keywords = {s.keyword: idx for idx, s in enumerate(all_suggestions)}

    for kw_idea in api_results:
        try:
            text_val = kw_idea.get("text", "")
            if not text_val:
                continue

            text_norm = text_utils.normalize_text(text_val)

            if (
                len(text_norm) < MIN_KEYWORD_LENGTH
                or len(text_norm.split()) > MAX_KEYWORD_WORDS
            ):
                continue

            metrics = kw_idea.get("keywordIdeaMetrics", {})
            volume = int(metrics.get("avgMonthlySearches", 0) or 0)
            raw_competition = metrics.get("competition", "UNKNOWN")
            competition_index = float(metrics.get("competitionIndex", 0) or 0) / 100.0

            new_suggestion = KeywordSuggestion(
                keyword=text_norm,
                volume=volume,
                competition=COMPETITION_MAP.get(
                    raw_competition, CompetitionLevel.UNKNOWN
                ),
                competitionIndex=competition_index,
            )

            if text_norm in existing_keywords:
                existing_idx = existing_keywords[text_norm]
                if volume > all_suggestions[existing_idx].volume:
                    all_suggestions[existing_idx] = new_suggestion
                    added_count += 1
            else:
                all_suggestions.append(new_suggestion)
                existing_keywords[text_norm] = len(all_suggestions) - 1
                added_count += 1

        except (ValueError, TypeError) as e:
            logger.warning(f"Validation error: {str(e)[:50]}")
            continue

    return added_count
