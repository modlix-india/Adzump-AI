import asyncio
import json
from structlog import get_logger
from collections import defaultdict

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import OptimizationResponse, CampaignRecommendation
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.gender import GoogleGenderAdapter
from core.services.recommendation_storage import recommendation_storage_service
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


class GenderOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.gender_adapter = GoogleGenderAdapter()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        campaign_product_map = (
            await campaign_mapping_service.get_campaign_product_mapping(client_code)
        )

        results = await asyncio.gather(
            *[
                self._process_google_account(
                    account=acc,
                    campaign_product_map=campaign_product_map,
                )
                for acc in accounts
            ]
        )

        all_recommendations = [rec for recs in results for rec in recs]

        await asyncio.gather(
            *[
                recommendation_storage_service.store(rec, client_code)
                for rec in all_recommendations
            ]
        )

        return {"recommendations": [r.model_dump() for r in all_recommendations]}

    async def _process_google_account(
        self,
        account: dict,
        campaign_product_map: dict,
    ) -> list[CampaignRecommendation]:
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        metrics = await self.gender_adapter.fetch_gender_metrics(
            account_id, parent_account_id
        )
        if not metrics:
            return []

        linked_metrics = self._filter_linked_google_campaigns(
            metrics, campaign_product_map
        )
        if not linked_metrics:
            logger.info(
                "No linked campaigns for account",
                account_id=account_id,
                total_campaigns=len(metrics),
            )
            return []

        grouped_by_adgroup = defaultdict(list)
        for metric_entry in linked_metrics:
            ad_group_id = str(metric_entry.get("ad_group", {}).get("id"))
            grouped_by_adgroup[ad_group_id].append(metric_entry)

        results = await asyncio.gather(
            *[
                self._analyze_google_metrics(
                    adgroup_metrics,
                    account_id,
                    parent_account_id,
                )
                for adgroup_metrics in grouped_by_adgroup.values()
            ]
        )

        return [rec for sublist in results for rec in sublist]

    def _filter_linked_google_campaigns(
        self, metrics: list, campaign_product_map: dict
    ) -> list:
        linked = []
        for metric_entry in metrics:
            campaign_id = str(metric_entry.get("campaign", {}).get("id"))
            if campaign_id in campaign_product_map:
                metric_entry["product_id"] = campaign_product_map[campaign_id]
                linked.append(metric_entry)
        return linked

    async def _analyze_google_metrics(
        self, metrics: list, account_id: str, parent_account_id: str
    ) -> list[CampaignRecommendation]:
        prompt = load_prompt("optimization/gender_optimization_prompt.txt")
        formatted = prompt.format(
            platform="GOOGLE",
            parent_account_id=parent_account_id,
            account_id=account_id,
            metrics=json.dumps(metrics, indent=2),
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted},
            ],
            model="gpt-4o-mini",
        )

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response) -> list[CampaignRecommendation]:
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()

        parsed = OptimizationResponse.model_validate_json(content)

        for campaign in parsed.recommendations:
            gender_recos = campaign.fields.gender or []

            # Group gender recommendations by ad_group_id
            grouped_by_adgroup = defaultdict(list)
            for gender_entry in gender_recos:
                grouped_by_adgroup[gender_entry.ad_group_id].append(gender_entry)

            blocked_adgroups = set()

            for ad_group_id, recos in grouped_by_adgroup.items():
                if all(r.recommendation == "REMOVE" for r in recos):
                    blocked_adgroups.add(ad_group_id)

            campaign.fields.gender = [
                g for g in gender_recos if g.ad_group_id not in blocked_adgroups
            ]

        return parsed.recommendations


gender_optimization_agent = GenderOptimizationAgent()
