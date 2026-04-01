from __future__ import annotations
import asyncio
import json
from structlog import get_logger
from services.trends.pytrends_service import pytrends_service
from services import openai_client
from utils import prompt_loader
from models.business_model import BusinessMetadata
from models.competitor_model import CompetitorKeyword


logger = get_logger(__name__)


class CompetitorInsightService:
    """Orchestrates keyword volume, competition, and trend analysis."""

    LLM_MODEL = "gpt-4o"
    CHUNK_SIZE = 5
    MAX_CANDIDATES_FOR_SCORING = 50

    def __init__(self):
        self.trends = pytrends_service
        self._trends_sem: asyncio.Semaphore | None = None

    @property
    def trends_sem(self) -> asyncio.Semaphore:
        """Lazily initialize the semaphore inside the active event loop."""
        if self._trends_sem is None:
            self._trends_sem = asyncio.Semaphore(10)
        return self._trends_sem

    async def enrich_competitor_keyword_trends(
        self,
        keywords: list[CompetitorKeyword],
    ) -> list[CompetitorKeyword]:
        """Add interest/momentum from Google Trends for the top candidates."""
        if not keywords:
            return []

        trend_candidates = sorted(
            keywords, key=lambda x: x.volume, reverse=True
        )[: self.MAX_CANDIDATES_FOR_SCORING]

        tasks = []
        for i in range(0, len(trend_candidates), self.CHUNK_SIZE):
            chunk = trend_candidates[i : i + self.CHUNK_SIZE]
            tasks.append(self._fetch_and_apply_trends(chunk))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "Competitor insight.trends_enriched",
            total=len(keywords),
            enriched=len(trend_candidates),
        )
        return keywords

    async def rate_keyword_potential(
        self,
        enriched_keywords: list[CompetitorKeyword],
        business_metadata: BusinessMetadata,
        competitor_names: list[str] | None = None,
    ) -> list[CompetitorKeyword]:
        """Score keywords using dual-track AI: Brand validation + Generic opportunity."""
        if not enriched_keywords:
            return []

        candidates = sorted(enriched_keywords, key=lambda x: x.volume, reverse=True)[
            : self.MAX_CANDIDATES_FOR_SCORING
        ]

        brand_kws = [kw for kw in candidates if kw.category == "Brand"]
        generic_kws = [kw for kw in candidates if kw.category != "Brand"]

        # Run both tracks in parallel
        tasks = []
        
        # Scoring Brand Keywords in chunks of 20
        for i in range(0, len(brand_kws), 20):
            tasks.append(
                self._score_brand_keywords(
                    brand_kws[i:i + 20], business_metadata, competitor_names or []
                )
            )
            
        # Scoring Generic Keywords in chunks of 20
        for i in range(0, len(generic_kws), 20):
            tasks.append(
                self._score_generic_keywords(generic_kws[i:i + 20], business_metadata)
            )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        scored = [kw for kw in candidates if kw.opportunity_score > 0]

        logger.info(
            "Competitor insight.scoring_complete",
            brand=len(brand_kws),
            generic=len(generic_kws),
            returned=len(scored),
        )
        return scored

    async def _fetch_and_apply_trends(self, chunk: list[CompetitorKeyword]) -> None:
        """Fetch trends for a chunk of keywords and apply the results."""
        chunk_terms = [kw.keyword for kw in chunk]

        async with self.trends_sem:
            try:
                interest_map = await self.trends.get_interest_over_time(chunk_terms)
                for kw in chunk:
                    metrics = interest_map.data.get(kw.keyword)
                    if metrics:
                        kw.trend_direction = metrics.trend_direction or "stable"
            except Exception as e:
                logger.warning(
                    "Competitor insight.chunk_failed",
                    terms=chunk_terms,
                    error=str(e)[:100],
                )

    async def _score_brand_keywords(
        self,
        keywords: list[CompetitorKeyword],
        business_metadata: BusinessMetadata,
        competitor_names: list[str],
    ) -> None:
        """Validate brand keywords against known competitor names using AI."""
        prompt = prompt_loader.format_prompt(
            "competitor/brand_validation_prompt.txt",
            competitor_names=", ".join(competitor_names),
            brand_name=business_metadata.brand_name,
            business_summary=business_metadata.business_summary,
            enriched_data=json.dumps(
                [
                    {
                        "keyword": kw.keyword,
                        "volume": kw.volume,
                        "competition": kw.competition,
                    }
                    for kw in keywords
                ]
            ),
        )
        await self._apply_llm_scores(prompt, keywords)

    async def _score_generic_keywords(
        self,
        keywords: list[CompetitorKeyword],
        business_metadata: BusinessMetadata,
    ) -> None:
        """Score generic keywords for relevance to the client's business."""
        prompt = prompt_loader.format_prompt(
            "competitor/opportunity_scoring_prompt.txt",
            brand_name=business_metadata.brand_name,
            business_type=business_metadata.business_type,
            primary_location=business_metadata.primary_location,
            unique_features=", ".join(business_metadata.unique_features),
            business_summary=business_metadata.business_summary,
            enriched_data=json.dumps(
                [
                    {
                        "keyword": kw.keyword,
                        "volume": kw.volume,
                        "competition": kw.competition,
                        "trend_direction": kw.trend_direction,
                    }
                    for kw in keywords
                ]
            ),
        )
        await self._apply_llm_scores(prompt, keywords)

    async def _apply_llm_scores(
        self, prompt: str, keywords: list[CompetitorKeyword]
    ) -> None:
        """
        Shared helper: call LLM and map scores back to keyword objects.
        Note: The message structure and prompt templates are optimized for 
        OpenAI Prompt Caching (Prefix Matching).
        """
        response = await openai_client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional Google Ads strategist and competitor analyst.",
                },
                {"role": "user", "content": prompt},
            ],
            model=self.LLM_MODEL,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content.strip())
        score_map = {
            r["keyword"].lower(): r
            for r in parsed.get("recommendations", [])
            if isinstance(r, dict) and "keyword" in r
        }

        for kw in keywords:
            scoring = score_map.get(kw.keyword.lower())
            if scoring:
                kw.opportunity_score = scoring.get("opportunity_score", 0)
                kw.recommended_action = scoring.get("recommended_action", "")
                kw.reasoning = scoring.get("reasoning", "")
                kw.competitor_advantage = scoring.get("competitor_advantage", "")


competitor_insight_service = CompetitorInsightService()
