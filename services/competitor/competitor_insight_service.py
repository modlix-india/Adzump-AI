import asyncio
import json
from typing import List, Optional
from structlog import get_logger
from adapters.google.optimization.keyword_planner import keyword_planner_adapter
from services.trends.pytrends_service import pytrends_service
from services.openai_client import chat_completion
from utils.prompt_loader import format_prompt
from models.business_model import BusinessMetadata
from models.competitor_model import (
    CompetitorKeyword,
    KeywordOpportunityScoring,
)
from exceptions.custom_exceptions import (
    AIProcessingException,
    TrendRateLimitException,
)

logger = get_logger(__name__)


class CompetitorInsightService:
    """Orchestrates keyword volume, competition, and trend analysis."""

    LLM_MODEL = "gpt-4o"
    CHUNK_SIZE = 5
    TREND_DELAY = 2
    TOP_SEEDS_COUNT = 5
    MAX_CANDIDATES_FOR_SCORING = 50

    DEFAULT_OPPORTUNITY_SCORE = 0
    DEFAULT_DIFFICULTY = "medium"
    DEFAULT_STRATEGIC_FIT = "moderate"
    MIN_VOLUME_THRESHOLD = 10

    def __init__(self):
        self.planner = keyword_planner_adapter
        self.trends = pytrends_service

    async def add_volume_and_trends(
        self,
        keywords: List[CompetitorKeyword],
        customer_id: str,
        login_customer_id: str,
        url: Optional[str] = None,
        skip_trends: bool = False,
    ) -> List[CompetitorKeyword]:
        """
        Add volume and trend data to a set of keywords.

        1. Fetch volume/competition from Keyword Planner.
        2. Fetch interest/momentum from Google Trends for top 20 keywords (if skip_trends is False).
        """
        unique_keyword_map = {
            kw.keyword.strip().lower(): kw for kw in keywords if kw.keyword
        }
        unique_keywords = list(unique_keyword_map.values())
        logger.info("enrichment.started", count=len(unique_keywords))

        # Rationale: We split enrichment into phases to decouple reliable/fast data (Google Ads)
        # from delayed/rate-limited data (Google Trends). This ensures that even if Trends fails,
        # we always return the core volume and competition metrics.

        # Keyword Planner (Fast & Mandatory)
        planner_results = await self.planner.generate_keyword_ideas(
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            seed_keywords=[kw.keyword for kw in unique_keywords],
            url=url,
        )
        planner_map = {p["keyword"].lower(): p for p in planner_results}

        for kw in unique_keywords:
            p_data = planner_map.get(kw.keyword.lower(), {})
            kw.volume = p_data.get("volume", 0)
            kw.competition = p_data.get("competition", "UNKNOWN")
            kw.competitionIndex = p_data.get("competitionIndex", 0.0)

        # Trends Interest (Limited & Resilient)
        # Rationale: PyTrends is prone to 429 rate limits and 5xx errors.
        # By processing it with a log-and-continue approach, we prevent
        # trend-related timeouts/failures from wiping out volume data.
        # We cap at 20 to keep the total request time under 90s.
        if not skip_trends:
            trend_candidates = sorted(
                unique_keywords, key=lambda x: (x.volume, x.relevance), reverse=True
            )[:20]

            if trend_candidates:
                await self._fetch_google_trends(trend_candidates)
        else:
            logger.info("enrichment.skipping_trends")

        # Volume Filtering
        # Rationale: We drop keywords with zero or negligible volume to focus
        # discovery on actionable search terms.
        high_volume_keywords = [
            kw for kw in unique_keywords if kw.volume >= self.MIN_VOLUME_THRESHOLD
        ]

        logger.info(
            "enrichment.complete",
            total=len(unique_keywords),
            kept=len(high_volume_keywords),
        )
        return high_volume_keywords

    async def _fetch_google_trends(self, keywords: List[CompetitorKeyword]) -> None:
        """Fetch Google Trends interest with a resilient chunks approach."""
        for i in range(0, len(keywords), self.CHUNK_SIZE):
            chunk = keywords[i : i + self.CHUNK_SIZE]
            chunk_texts = [kw.keyword for kw in chunk]

            try:
                trend_response = await self.trends.get_interest_over_time(chunk_texts)
                for kw in chunk:
                    t_data = trend_response.data.get(kw.keyword)
                    if t_data:
                        kw.trend_direction = t_data.trend_direction

            except TrendRateLimitException:
                logger.warning("enrichment.trends_rate_limited", chunk=chunk_texts)
            except Exception as e:
                logger.warning(
                    "enrichment.chunk_failed", error=str(e), chunk=chunk_texts
                )

            if i + self.CHUNK_SIZE < len(keywords):
                await asyncio.sleep(self.TREND_DELAY)

    async def rate_keyword_potential(
        self,
        enriched_keywords: List[CompetitorKeyword],
        business_metadata: BusinessMetadata,
    ) -> List[CompetitorKeyword]:
        """Rate the potential of top 50 keywords using AI."""
        if not enriched_keywords:
            return []

        candidates = sorted(enriched_keywords, key=lambda x: x.volume, reverse=True)[
            : self.MAX_CANDIDATES_FOR_SCORING
        ]

        prompt = format_prompt(
            "competitor/opportunity_scoring_prompt.txt",
            brand_name=business_metadata.brand_name,
            business_type=business_metadata.business_type,
            primary_location=business_metadata.primary_location,
            unique_features=", ".join(business_metadata.unique_features),
            business_summary=business_metadata.business_summary,
            enriched_data=json.dumps([kw.model_dump() for kw in candidates]),
        )

        try:
            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.LLM_MODEL,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(response.choices[0].message.content.strip())
            results = parsed.get("recommendations", [])
            recommendations = [
                KeywordOpportunityScoring(**r)
                for r in results
                if isinstance(r, dict) and "keyword" in r
            ]

            score_map = {r.keyword.lower(): r for r in recommendations}
            for kw in candidates:
                scoring = score_map.get(kw.keyword.lower())
                if scoring:
                    kw.opportunity_score = scoring.opportunity_score
                    kw.difficulty = scoring.difficulty
                    kw.strategic_fit = scoring.strategic_fit
                    kw.recommended_action = scoring.recommended_action
                    kw.reasoning = scoring.reasoning

            # Quality Filter: Only return keywords with actionable potential
            scored_candidates = [kw for kw in candidates if kw.opportunity_score > 0]

            logger.info(
                "enrichment.scoring_complete",
                total=len(candidates),
                filtered=len(candidates) - len(scored_candidates),
            )
            return scored_candidates

        except Exception as e:
            logger.error("enrichment.scoring_failed", error=str(e))
            raise AIProcessingException(
                message=f"Keyword opportunity scoring failed: {str(e)}"
            ) from e


competitor_insight_service = CompetitorInsightService()
