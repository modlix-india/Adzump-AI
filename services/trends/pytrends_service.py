import asyncio
import statistics
from typing import List
from datetime import datetime
import structlog
from pytrends.request import TrendReq
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


class PyTrendsService:
    """Service for Google Trends data using pytrends."""

    def __init__(self, language: str = "en-US", timezone: int = 360):
        self._language = language
        self._timezone = timezone
        self._pytrends_instance = (
            None  # Lazy initialize to avoid startup network timeout
        )
        self._lock = asyncio.Lock()

    @property
    def client(self) -> TrendReq:
        """
        Lazy-initialize the TrendReq client only when needed.
        Note: This is intended for use within thread-safe or synchronous contexts.
        """
        if self._pytrends_instance is None:
            logger.info("pytrends.lazy_init", language=self._language)
            self._pytrends_instance = TrendReq(hl=self._language, tz=self._timezone)
        return self._pytrends_instance

    async def get_interest_over_time(
        self, keywords: List[str], timeframe: str = DEFAULT_TIMEFRAME
    ) -> TrendInterestResponse:
        """
        Get interest over time for up to 5 keywords.

        Args:
            keywords: List of keywords (max 5 per request).
            timeframe: Time period string e.g. 'today 12-m', 'today 3-m'.

        Returns:
            TrendInterestResponse with per-keyword metrics.
        """
        if not keywords:
            return TrendInterestResponse(
                success=True, keywords=keywords, timeframe=timeframe
            )

        if len(keywords) > MAX_KEYWORDS:
            logger.warning(
                "pytrends.truncate_keywords", original=len(keywords), limit=MAX_KEYWORDS
            )
            keywords = keywords[:MAX_KEYWORDS]

        try:

            def _fetch():
                client = self.client
                client.build_payload(
                    kw_list=keywords, timeframe=timeframe, geo="", gprop=""
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
                    avg_interest=round(avg, 2),
                    max_interest=max(values) if values else 0,
                    min_interest=min(values) if values else 0,
                    current_interest=values[-1] if values else 0,
                    trend_direction=self._calculate_trend(values),
                    trend_slope=self._calculate_slope(values),
                )

            return result

        except Exception as e:
            self._handle_exception(e, context={"keywords": keywords})

    async def get_related_queries(self, keyword: str) -> RelatedQueriesResponse:
        """
        Get top and rising related queries for a single keyword.

        Args:
            keyword: The seed keyword to look up.

        Returns:
            RelatedQueriesResponse with top and rising query lists.
        """
        try:

            def _fetch():
                client = self.client
                client.build_payload(
                    kw_list=[keyword], timeframe=DEFAULT_TIMEFRAME, geo="", gprop=""
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

            return result

        except Exception as e:
            self._handle_exception(e, context={"keyword": keyword})

    async def get_trending_searches(
        self, country: str = "united_states"
    ) -> TrendingSearchResponse:
        """
        Get today's top 20 trending searches for a country.

        Args:
            country: Country name slug e.g. 'united_states', 'united_kingdom'.

        Returns:
            TrendingSearchResponse with a list of trending search terms.
        """
        try:
            trending_df = await asyncio.to_thread(
                self.client.trending_searches, pn=country
            )

            today = datetime.now().strftime("%Y-%m-%d")

            if trending_df is None or trending_df.empty:
                return TrendingSearchResponse(success=True, country=country, date=today)

            return TrendingSearchResponse(
                success=True,
                country=country,
                date=today,
                trending_searches=trending_df[0].tolist()[:20],
            )

        except Exception as e:
            self._handle_exception(e, context={"country": country})

    def _handle_exception(self, e: Exception, context: dict) -> None:
        """Raise the appropriate typed exception based on the error."""
        if "429" in str(e):
            logger.error("pytrends.rate_limit_hit", **context)
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

        quarter = max(len(values) // 4, 1)
        first_avg = statistics.mean(values[:quarter])
        last_avg = statistics.mean(values[-quarter:])

        if first_avg == 0:
            return "stable"

        change = ((last_avg - first_avg) / first_avg) * 100

        thresholds = [
            (15, "rising"),
            (-15, "stable"),
        ]
        return next(
            (label for threshold, label in thresholds if change > threshold),
            "declining",
        )

    def _calculate_slope(self, values: List[int]) -> float:
        """Calculate percentage change from first to last value."""
        if len(values) < 2 or values[0] == 0:
            return 0.0
        return round(((values[-1] - values[0]) / values[0]) * 100, 2)


# Singleton instance
pytrends_service = PyTrendsService()
