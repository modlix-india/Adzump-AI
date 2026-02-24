import asyncio
import json
from collections import defaultdict
from structlog import get_logger

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import (
    OptimizationResponse,
    CampaignRecommendation,
)
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.age import GoogleAgeAdapter
from core.services.recommendation_storage import recommendation_storage_service
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


class AgeOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.age_adapter = GoogleAgeAdapter()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        campaign_product_map = (
            await campaign_mapping_service.get_campaign_mapping_with_summary(
                client_code
            )
        )

        results = await asyncio.gather(
            *[
                self._process_google_account(
                    account=acc, campaign_product_map=campaign_product_map
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
        """Process a single Google Ads account."""
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        # Single call — adapter fetches performance + targeting in parallel internally
        metrics = await self.age_adapter.fetch_age_metrics(
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
                total_rows=len(metrics),
            )
            return []

        # Rebuild targeting_map from merged rows (needed for post-LLM filter)
        targeting_map: dict[str, set[str]] = {}
        for row in linked_metrics:
            if row["is_targeted"]:
                targeting_map.setdefault(row["ad_group_id"], set()).add(
                    row["age_range"]
                )

        # Log targeting state per ad group
        ad_group_ids = {row["ad_group_id"] for row in linked_metrics}
        for ad_group_id in ad_group_ids:
            targeted = targeting_map.get(ad_group_id, set())
            logger.info(
                "Age targeting state",
                account_id=account_id,
                ad_group_id=ad_group_id,
                targeted=sorted(targeted),
                total_targeted=len(targeted),
            )

        # Group by ad group
        grouped: dict[str, list] = defaultdict(list)
        for row in linked_metrics:
            grouped[row["ad_group_id"]].append(row)

        # One LLM call per ad group, all in parallel — isolated failures
        results = await asyncio.gather(
            *[
                self._analyze_adgroup_metrics(
                    adgroup_metrics, account_id, parent_account_id
                )
                for adgroup_metrics in grouped.values()
            ],
            return_exceptions=True,
        )

        all_recs: list[CampaignRecommendation] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Ad group LLM analysis failed", error=str(result))
                continue
            all_recs.extend(result)

        return self._filter_recommendations(all_recs, targeting_map)

    def _filter_linked_google_campaigns(
        self, metrics: list, campaign_product_map: dict
    ) -> list:
        """Filter metrics to only campaigns with linked products."""
        linked = []
        for m in metrics:
            campaign_id = m.get("campaign_id", "")
            if campaign_id in campaign_product_map:
                mapping_data = campaign_product_map[campaign_id]
                if isinstance(mapping_data, str):
                    m["product_id"] = mapping_data
                    m["product_summary"] = ""
                else:
                    m["product_id"] = mapping_data.get("product_id", "")
                    m["product_summary"] = mapping_data.get("summary", "")
                linked.append(m)
        return linked

    async def _analyze_adgroup_metrics(
        self,
        metrics: list[dict],
        account_id: str,
        parent_account_id: str,
    ) -> list[CampaignRecommendation]:
        """Call LLM for a single ad group's age range data and return parsed recommendations."""
        first = metrics[0]
        product_context = (
            first.get("product_summary") or "No product information available"
        )

        # Build resource_name lookup for backfill after LLM parse
        # (ad_group_id, age_range) → resource_name
        resource_name_map: dict[tuple[str, str], str] = {
            (row["ad_group_id"], row["age_range"]): row["resource_name"]
            for row in metrics
            if row.get("resource_name")
        }

        prompt = load_prompt("optimization/age_optimization_prompt.txt")
        formatted = prompt.format(
            platform="GOOGLE",
            parent_account_id=parent_account_id,
            account_id=account_id,
            metrics=json.dumps(metrics, indent=2),
            product_context=product_context,
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted},
            ],
            model="gpt-4o-mini",
        )

        recs = self._parse_llm_response(response)

        # Backfill resource_name on REMOVE recommendations the LLM forgot to include
        for rec in recs:
            for age_rec in rec.fields.age or []:
                if age_rec.recommendation == "REMOVE" and not age_rec.resource_name:
                    age_rec.resource_name = resource_name_map.get(
                        (age_rec.ad_group_id, age_rec.age_range)
                    )

        return recs

    def _parse_llm_response(self, response) -> list[CampaignRecommendation]:
        """Parse and validate LLM response."""
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()

        parsed = OptimizationResponse.model_validate_json(content)
        for rec in parsed.recommendations:
            rec.campaign_type = "SEARCH"
        return list(parsed.recommendations)

    def _filter_recommendations(
        self,
        recommendations: list[CampaignRecommendation],
        targeting_map: dict[str, set[str]],
    ) -> list[CampaignRecommendation]:
        filtered_recs = []

        for rec in recommendations:
            if not rec.fields.age:
                continue

            ad_group_id = rec.fields.age[0].ad_group_id
            if not ad_group_id:
                continue

            currently_targeted = {
                r
                for r in targeting_map.get(ad_group_id, set())
                if r != "AGE_RANGE_UNDETERMINED"
            }

            llm_adds = [
                a.age_range for a in rec.fields.age if a.recommendation == "ADD"
            ]
            llm_removes = [
                r.age_range for r in rec.fields.age if r.recommendation == "REMOVE"
            ]
            logger.info(
                "LLM suggestions received",
                ad_group_id=ad_group_id,
                campaign_id=rec.campaign_id,
                suggested_to_add=llm_adds,
                suggested_to_remove=llm_removes,
                total_suggestions=len(rec.fields.age),
            )

            seen: set[tuple] = set()
            valid_adds = []
            valid_removes = []

            for age_rec in rec.fields.age:
                key = (age_rec.ad_group_id, age_rec.age_range, age_rec.recommendation)
                if key in seen:
                    logger.debug(
                        "Filtered duplicate recommendation",
                        ad_group_id=ad_group_id,
                        age_range=age_rec.age_range,
                        recommendation=age_rec.recommendation,
                    )
                    continue
                seen.add(key)

                if age_rec.recommendation == "ADD":
                    if age_rec.age_range not in currently_targeted:
                        valid_adds.append(age_rec)
                    else:
                        logger.debug(
                            "Filtered ADD - already targeted",
                            ad_group_id=ad_group_id,
                            age_range=age_rec.age_range,
                        )
                elif age_rec.recommendation == "REMOVE":
                    if age_rec.age_range in currently_targeted:
                        valid_removes.append(age_rec)
                    else:
                        logger.debug(
                            "Filtered REMOVE - not targeted",
                            ad_group_id=ad_group_id,
                            age_range=age_rec.age_range,
                        )

            # All-REMOVE guard: don't zero out targeting for an ad group
            remove_ranges = {r.age_range for r in valid_removes}
            if remove_ranges and remove_ranges >= currently_targeted and not valid_adds:
                logger.warning(
                    "Skipping ad group - recommendations would remove all targeting",
                    ad_group_id=ad_group_id,
                    campaign_id=rec.campaign_id,
                    would_remove=sorted(remove_ranges),
                )
                continue

            final_recs = valid_adds + valid_removes
            if not final_recs:
                continue

            logger.info(
                "Final age optimization recommendations",
                ad_group_id=ad_group_id,
                campaign_id=rec.campaign_id,
                final_to_add=[a.age_range for a in valid_adds],
                final_to_remove=[r.age_range for r in valid_removes],
                add_count=len(valid_adds),
                remove_count=len(valid_removes),
            )

            rec.fields.age = final_recs
            filtered_recs.append(rec)

        return filtered_recs


age_optimization_agent = AgeOptimizationAgent()
