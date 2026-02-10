import asyncio
from structlog import get_logger

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import (
    OptimizationFields,
    CampaignRecommendation,
    KeywordRecommendation,
)
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.keyword import GoogleKeywordAdapter
from core.services.recommendation_storage import recommendation_storage_service
from core.services.metric_performance_evaluator import MetricPerformanceEvaluator
from core.services.metric_evaluator_config import KEYWORD_CONFIG, group_by_campaign
from core.services.business_context_service import business_context_service
from core.keyword.idea_service import KeywordIdeaService

logger = get_logger(__name__)


class KeywordOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.keyword_adapter = GoogleKeywordAdapter()
        self.evaluator = MetricPerformanceEvaluator(KEYWORD_CONFIG)
        self.keyword_idea_service = KeywordIdeaService()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts, campaign_product_mapping = await asyncio.gather(
            self.accounts_adapter.fetch_accessible_accounts(client_code),
            campaign_mapping_service.get_campaign_mapping_with_summary(client_code),
        )
        if not accounts:
            logger.info("keyword_opt_no_accounts", client_code=client_code)
            return {"recommendations": []}

        await business_context_service.extract_contexts_by_product(campaign_product_mapping)

        #TO:DO waits for all recommendations to be generated then stores them think for better performance
        results = await asyncio.gather(
            *[self._process_account(acc, campaign_product_mapping) for acc in accounts]
        )
        all_recommendations = [rec for recs in results for rec in recs]

        await asyncio.gather(
            *[
                recommendation_storage_service.store(rec, client_code)
                for rec in all_recommendations
            ]
        )

        logger.info("keyword_opt_complete", total=len(all_recommendations))
        return {"recommendations": [r.model_dump() for r in all_recommendations]}

    async def _process_account(
        self, account: dict, campaign_product_mapping: dict
    ) -> list[CampaignRecommendation]:
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        keywords = await self.keyword_adapter.fetch_keyword_metrics(
            account_id, parent_account_id
        )
        if not keywords:
            return []

        linked_keywords = [kw for kw in keywords if kw["campaign_id"] in campaign_product_mapping]
        scored_keywords = self.evaluator.evaluate(linked_keywords)
        self.evaluator.mark_top_performers(scored_keywords)
        keywords_by_campaign = group_by_campaign(scored_keywords, campaign_product_mapping)

        results = await asyncio.gather(
            *[
                self._analyze_campaign(campaign_group, account_id, parent_account_id)
                for campaign_group in keywords_by_campaign
            ]
        )
        return [rec for rec in results if rec is not None]

    async def _analyze_campaign(
        self,
        campaign_group: dict,
        account_id: str,
        parent_id: str,
    ) -> CampaignRecommendation | None:
        """Run Track A (review poor keywords) + Track B (suggest new keywords)."""
        optimizations = self._review_poor_keywords(campaign_group)
        suggestions = await self.keyword_idea_service.suggest_keywords(
            campaign_group, account_id, parent_id
        )

        all_keywords = optimizations + suggestions
        if not all_keywords:
            return None

        entries = campaign_group["entries"]
        return CampaignRecommendation(
            platform="GOOGLE",
            parent_account_id=parent_id,
            account_id=account_id,
            product_id=campaign_group.get("product_id", ""),
            campaign_id=campaign_group.get("campaign_id", ""),
            campaign_name=campaign_group.get("name", ""),
            campaign_type=entries[0].get("campaign_type", "SEARCH") if entries else "",
            completed=False,
            fields=OptimizationFields(keywords=all_keywords),
        )

    @staticmethod
    def _review_poor_keywords(
        campaign_group: dict,
    ) -> list[KeywordRecommendation]:
        """Track A: PAUSE critical poor keywords.

        No LLM call — evaluator already computes strength, is_critical, and
        reason. Only critical poor keywords (high spend / high clicks with
        zero conversions) get paused; non-critical poor ones are left as-is.
        """
        optimizations: list[KeywordRecommendation] = []
        for entry in campaign_group["entries"]:
            if entry.get("strength") != "poor" or not entry.get("is_critical"):
                continue

            optimizations.append(
                KeywordRecommendation(
                    text=entry["keyword"],
                    match_type=entry.get("match_type", ""),
                    ad_group_id=entry.get("ad_group_id", ""),
                    ad_group_name=entry.get("ad_group_name", ""),
                    criterion_id=entry.get("criterion_id"),
                    recommendation="PAUSE",
                    reason=entry.get("reason", ""),
                    metrics=entry.get("metrics"),
                    quality_score=entry.get("quality_score"),
                    origin="KEYWORD",
                )
            )

        return optimizations

keyword_optimization_agent = KeywordOptimizationAgent()
