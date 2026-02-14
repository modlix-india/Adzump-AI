# TODO: V2 — include proximity (radius) targeting options and rethink evaluation strategy
import asyncio

from structlog import get_logger

from core.models.optimization import (
    CampaignRecommendation,
    OptimizationFields,
)
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.location import GoogleLocationAdapter
from core.services.location_evaluator import LocationEvaluator
from core.services.recommendation_storage import recommendation_storage_service

logger = get_logger(__name__)


class LocationOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.location_adapter = GoogleLocationAdapter()
        self.evaluator = LocationEvaluator()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        results = await asyncio.gather(*[
            self._process_account(acc) for acc in accounts
        ])
        all_recs = [rec for recs in results for rec in recs]

        for rec in all_recs:
            await recommendation_storage_service.store(rec, client_code)

        return {"recommendations": [r.model_dump() for r in all_recs]}

    async def _process_account(
        self, account: dict
    ) -> list[CampaignRecommendation]:
        account_id = account["customer_id"]
        parent_id = account["login_customer_id"]

        targets, performance = await asyncio.gather(
            self.location_adapter.fetch_campaign_location_targets(account_id, parent_id),
            self.location_adapter.fetch_location_performance(account_id, parent_id),
        )
        if not targets or not performance:
            return []

        all_geo_constants = list({
            geo for geo_metrics in performance.values() for geo in geo_metrics
        })
        geo_details = await self.location_adapter.fetch_geo_target_details(
            account_id, parent_id, all_geo_constants
        )

        recommendations = []
        for campaign_id, campaign_data in targets.items():
            if campaign_id not in performance:
                continue

            location_recs = self.evaluator.evaluate_campaign(
                campaign_id,
                campaign_data["targeted_locations"],
                performance[campaign_id],
                geo_details,
            )
            if not location_recs:
                continue

            recommendations.append(CampaignRecommendation(
                platform="GOOGLE",
                parent_account_id=parent_id,
                account_id=account_id,
                product_id=None,
                campaign_id=campaign_id,
                campaign_name=campaign_data["campaign_name"],
                campaign_type=campaign_data.get("campaign_type", "SEARCH"),
                completed=False,
                fields=OptimizationFields(
                    locationOptimizations=location_recs,
                ),
            ))

        logger.info(
            "Location optimization processed",
            account_id=account_id,
            campaigns_with_recs=len(recommendations),
        )
        return recommendations


location_optimization_agent = LocationOptimizationAgent()
