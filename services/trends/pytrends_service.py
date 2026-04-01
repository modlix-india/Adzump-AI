import asyncio
import statistics
import time
from typing import List, Any, Dict, Optional
from datetime import datetime
import structlog
from pytrends.request import TrendReq
from core.infrastructure.retry_handler import async_retry
from exceptions.custom_exceptions import (
    TrendServiceException,
    TrendRateLimitException,
)
from models.competitor_model import (
    TrendInterestMetrics,
    TrendInterestResponse,
    RelatedQueriesResponse,
    TrendingSearchResponse,
    RelatedQuery,
)

logger = structlog.get_logger(__name__)

MAX_KEYWORDS = 5
DEFAULT_TIMEFRAME = "today 12-m"

# Configured for robust rate-limit handling.
# 3 attempts with a 5s initial backoff provides a good balance for Google Trends.
_retry_on_rate_limit = async_retry(
    max_attempts=3, initial_backoff=5, exceptions=(TrendRateLimitException,)
)


class PyTrendsService:
    """Service for Google Trends data using pytrends with caching and local clients."""

    # Calculation Constants
    TREND_WINDOW_DIVISOR = 4  # Divide timeframe into 4 quarters for trend analysis
    TREND_RISE_THRESHOLD = 15.0  # Percentage increase to be considered 'rising'
    TREND_DECLINE_THRESHOLD = -15.0  # Percentage decrease to be considered 'declining'
    PRECISION_DECIMALS = 2  # Decimal places for interest metrics

    # Caching Constants
    CACHE_TTL = 3600  # 1 hour in seconds

    def __init__(self, language: str = "en-US", timezone: int = 360):
        self._language = language
        self._timezone = timezone
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Retrieve a valid item from the cache."""
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry["expiry"]:
                logger.debug("pytrends.cache_hit", key=key)
                return entry["data"]
            # Clear expired item
            del self._cache[key]
        return None

    def _set_to_cache(self, key: str, data: Any) -> None:
        """Store an item in the cache with a TTL(Time To Live)."""
        self._cache[key] = {"data": data, "expiry": time.time() + self.CACHE_TTL}

    def _create_client(self) -> TrendReq:
        """Create a fresh TrendReq instance for a single request to ensure thread safety."""
        return TrendReq(hl=self._language, tz=self._timezone)

    @_retry_on_rate_limit
    async def get_interest_over_time(
        self, keywords: List[str], timeframe: str = DEFAULT_TIMEFRAME
    ) -> TrendInterestResponse:
        """Get interest over time for up to 5 keywords (localized to India)."""
        if not keywords:
            return TrendInterestResponse(
                success=True, keywords=keywords, timeframe=timeframe
            )

        keywords = sorted(list(set(keywords)))[:MAX_KEYWORDS]
        cache_key = f"interest:{timeframe}:" + ":".join(keywords)

        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:

            def _fetch():
                # Important: Use a local client to avoid payload mixups between parallel requests
                client = self._create_client()
                client.build_payload(
                    kw_list=keywords, timeframe=timeframe, geo="IN", gprop=""
                )
                return client.interest_over_time()

            interest_df = await asyncio.to_thread(_fetch)

            result = TrendInterestResponse(
                success=True, keywords=keywords, timeframe=timeframe
            )

            if interest_df is None or interest_df.empty:
                logger.warning("pytrends.empty_response", keywords=keywords)
                return result

            for keyword in keywords:
                if keyword not in interest_df.columns:
                    continue

                values = interest_df[keyword].tolist()
                dates = interest_df.index.strftime("%Y-%m-%d").tolist()
                avg = statistics.mean(values) if values else 0

                result.data[keyword] = TrendInterestMetrics(
                    values=values,
                    dates=dates,
                    avg_interest=round(avg, self.PRECISION_DECIMALS),
                    max_interest=max(values) if values else 0,
                    min_interest=min(values) if values else 0,
                    current_interest=values[-1] if values else 0,
                    trend_direction=self._calculate_trend(values),
                    trend_slope=self._calculate_slope(values),
                )

            self._set_to_cache(cache_key, result)
            return result

        except Exception as e:
            self._handle_exception(e, context={"keywords": keywords})

    @_retry_on_rate_limit
    async def get_related_queries(self, keyword: str) -> RelatedQueriesResponse:
        """Get top and rising related queries for a single keyword (localized to India)."""
        cache_key = f"related:{keyword}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:

            def _fetch():
                client = self._create_client()
                client.build_payload(
                    kw_list=[keyword], timeframe=DEFAULT_TIMEFRAME, geo="IN", gprop=""
                )
                return client.related_queries()

            related_data = await asyncio.to_thread(_fetch)
            result = RelatedQueriesResponse(success=True, keyword=keyword)

            if not isinstance(related_data, dict) or keyword not in related_data:
                return result

            keyword_data = related_data[keyword]

            # Top queries
            top_df = keyword_data.get("top")
            if top_df is not None and not top_df.empty:
                result.top = [
                    RelatedQuery(query=row["query"], value=int(row["value"]))
                    for _, row in top_df.head(5).iterrows()
                ]

            # Rising queries
            rising_df = keyword_data.get("rising")
            if rising_df is not None and not rising_df.empty:
                result.rising = [
                    RelatedQuery(query=row["query"], value=row["value"])
                    for _, row in rising_df.head(5).iterrows()
                ]

            self._set_to_cache(cache_key, result)
            return result

        except Exception as e:
            self._handle_exception(e, context={"keyword": keyword})

    @_retry_on_rate_limit
    async def get_trending_searches(
        self, country: str = "india"
    ) -> TrendingSearchResponse:
        """Get today's top 20 trending searches for a country (defaults to India)."""
        cache_key = f"trending:{country}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            client = self._create_client()
            trending_df = await asyncio.to_thread(client.trending_searches, pn=country)

            today = datetime.now().strftime("%Y-%m-%d")

            if trending_df is None or trending_df.empty:
                return TrendingSearchResponse(success=True, country=country, date=today)

            result = TrendingSearchResponse(
                success=True,
                country=country,
                date=today,
                trending_searches=trending_df[0].tolist()[:20],
            )
            self._set_to_cache(cache_key, result)
            return result

        except Exception as e:
            self._handle_exception(e, context={"country": country})

    def _handle_exception(self, e: Exception, context: dict) -> None:
        """Raise the appropriate typed exception based on the error.

        Rate-limit errors (429) are raised as TrendRateLimitException so that
        the @_retry_on_rate_limit decorator on the calling method can catch them
        by type and retry the request after a backoff delay.
        """
        if "429" in str(e):
            # Warning not error — this is a retryable condition, the decorator
            # will attempt the request again before giving up.
            logger.warning("pytrends.rate_limit_hit", **context)
            raise TrendRateLimitException(details=context) from e

        logger.error("pytrends.request_failed", error=str(e), **context)
        raise TrendServiceException(
            message=f"Google Trends request failed: {str(e)}",
            details=context,
        ) from e

    def _calculate_trend(self, values: List[int]) -> str:
        """Classify trend direction by comparing first vs last quarter averages."""
        if len(values) < 2:
            return "stable"

        quarter = max(len(values) // self.TREND_WINDOW_DIVISOR, 1)
        first_avg = statistics.mean(values[:quarter])
        last_avg = statistics.mean(values[-quarter:])

        if first_avg == 0:
            return "stable"

        change = ((last_avg - first_avg) / first_avg) * 100

        thresholds = [
            (self.TREND_RISE_THRESHOLD, "rising"),
            (self.TREND_DECLINE_THRESHOLD, "stable"),
        ]
        return next(
            (label for threshold, label in thresholds if change > threshold),
            "declining",
        )

    def _calculate_slope(self, values: List[int]) -> float:
        """Calculate percentage change from first to last value."""
        if len(values) < 2 or values[0] == 0:
            return 0.0
        return round(
            ((values[-1] - values[0]) / values[0]) * 100, self.PRECISION_DECIMALS
        )


# Singleton instance
pytrends_service = PyTrendsService()
