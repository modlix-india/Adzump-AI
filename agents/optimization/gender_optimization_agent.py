import asyncio
import json
from structlog import get_logger
from collections import defaultdict

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import (
    GenderFieldRecommendation,
    CampaignRecommendation,
    OptimizationFields,
)
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
                self._process_account(
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

        return {"recommendations": [rec.model_dump() for rec in all_recommendations]}

    async def _process_account(
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

        linked_metrics = self._filter_linked_campaigns(metrics, campaign_product_map)
        if not linked_metrics:
            logger.info(
                "No linked campaigns for account",
                account_id=account_id,
                total_campaigns=len(metrics),
            )
            return []

        grouped_by_adgroup = defaultdict(list)
        for metric_entry in linked_metrics:
            grouped_by_adgroup[metric_entry["ad_group_id"]].append(metric_entry)

        results = await asyncio.gather(
            *[
                self._analyze_adgroup_metrics(
                    adgroup_metrics, account_id, parent_account_id
                )
                for adgroup_metrics in grouped_by_adgroup.values()
            ]
        )

        return [rec for sublist in results for rec in sublist]

    async def _analyze_adgroup_metrics(
        self,
        metrics: list,
        account_id: str,
        parent_account_id: str,
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

        active_genders, resource_name_map = _build_targeting_lookups(metrics)
        gender_recs = self._parse_llm_response(
            response, active_genders, resource_name_map
        )
        if not gender_recs:
            return []

        first = metrics[0]
        return [
            CampaignRecommendation(
                _id=None,
                platform="google_ads",
                parent_account_id=parent_account_id,
                account_id=account_id,
                product_id=first.get("product_id"),
                campaign_id=first["campaign_id"],
                campaign_name=first.get("campaign_name", ""),
                campaign_type=first.get("campaign_type", ""),
                fields=OptimizationFields(gender=gender_recs),
            )
        ]

    def _parse_llm_response(
        self,
        response,
        active_genders: dict[str, set[str]],
        resource_name_map: dict[tuple[str, str], str],
    ) -> list[GenderFieldRecommendation]:
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()
        data = json.loads(content)

        recs = [
            GenderFieldRecommendation.model_validate(rec)
            for rec in data.get("gender", [])
        ]

        for rec in recs:
            if rec.recommendation == "REMOVE" and not rec.resource_name:
                rec.resource_name = resource_name_map.get(
                    (rec.ad_group_id, rec.gender_type)
                )

        return _filter_gender_recs(recs, active_genders)

    @staticmethod
    def _filter_linked_campaigns(metrics: list, campaign_product_map: dict) -> list:
        linked = []
        for metric_entry in metrics:
            campaign_id = metric_entry["campaign_id"]
            if campaign_id in campaign_product_map:
                metric_entry["product_id"] = campaign_product_map[campaign_id]
                linked.append(metric_entry)
        return linked


def _build_targeting_lookups(
    metrics: list,
) -> tuple[dict[str, set[str]], dict[tuple[str, str], str]]:
    active_genders: dict[str, set[str]] = {}
    resource_name_map: dict[tuple[str, str], str] = {}

    for entry in metrics:
        ad_group_id = entry["ad_group_id"]

        for gender in entry.get("targeted_genders", []):
            active_genders.setdefault(ad_group_id, set()).add(gender)

        resource_name = entry.get("resource_name")
        if resource_name:
            resource_name_map[(ad_group_id, entry["gender_type"])] = resource_name

    return active_genders, resource_name_map


def _filter_gender_recs(
    recs: list[GenderFieldRecommendation],
    active_genders: dict[str, set[str]],
) -> list[GenderFieldRecommendation]:
    by_adgroup: dict[str, list] = defaultdict(list)
    for rec in recs:
        by_adgroup[rec.ad_group_id].append(rec)

    all_remove_adgroups = {
        ad_group_id
        for ad_group_id, group in by_adgroup.items()
        if all(rec.recommendation == "REMOVE" for rec in group)
    }

    return [
        rec
        for rec in recs
        if rec.ad_group_id not in all_remove_adgroups
        and not (
            rec.recommendation == "ADD"
            and rec.gender_type in active_genders.get(rec.ad_group_id, set())
        )
        and not (rec.recommendation == "REMOVE" and not rec.resource_name)
    ]


gender_optimization_agent = GenderOptimizationAgent()
