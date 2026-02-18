import asyncio
import json
from structlog import get_logger

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import (
    OptimizationResponse,
    CampaignRecommendation,
)
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.age import GoogleAgeAdapter, ALL_AGE_RANGES
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

        # Fetch both campaign→product mapping and product summaries
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
                total_campaigns=len(metrics),
            )
            return []

        # Fetch current age targeting state for all campaigns
        campaign_ids = list(
            set(str(m.get("campaign", {}).get("id")) for m in linked_metrics)
        )
        targeting_map = await self.age_adapter.fetch_age_targeting(
            account_id, parent_account_id, campaign_ids
        )

        # Log targeting state for each ad group
        for ad_group_id, targeted_ranges in targeting_map.items():
            untargeted_ranges = set(ALL_AGE_RANGES) - targeted_ranges
            logger.info(
                "Age targeting state",
                account_id=account_id,
                ad_group_id=ad_group_id,
                previously_targeted=sorted(list(targeted_ranges)),
                remaining_untargeted=sorted(list(untargeted_ranges)),
                total_targeted=len(targeted_ranges),
                total_untargeted=len(untargeted_ranges),
            )

        recommendations = await self._analyze_google_metrics(
            linked_metrics, account_id, parent_account_id, targeting_map
        )

        return self._filter_recommendations(recommendations, targeting_map)

    def _filter_linked_google_campaigns(
        self, metrics: list, campaign_product_map: dict
    ) -> list:
        """Filter metrics to only campaigns with linked products."""
        linked = []
        for m in metrics:
            campaign_id = str(m.get("campaign", {}).get("id"))
            if campaign_id in campaign_product_map:
                mapping_data = campaign_product_map[campaign_id]
                # Handle both string (old) and dict (new) formats
                if isinstance(mapping_data, str):
                    m["product_id"] = mapping_data
                    m["product_summary"] = ""
                else:
                    m["product_id"] = mapping_data.get("product_id", "")
                    m["product_summary"] = mapping_data.get("summary", "")
                linked.append(m)
        return linked

    async def _analyze_google_metrics(
        self,
        metrics: list,
        account_id: str,
        parent_account_id: str,
        targeting_map: dict[str, set[str]],
    ) -> list[CampaignRecommendation]:
        """Send metrics to LLM for analysis and return parsed recommendations."""
        # Build targeting state summary and untargeted ranges for prompt
        targeting_summary = self._build_targeting_summary(metrics, targeting_map)
        untargeted_summary = self._build_untargeted_summary(metrics, targeting_map)
        product_context = self._build_product_context(metrics)

        prompt = load_prompt("optimization/age_optimization_prompt.txt")
        formatted = prompt.format(
            platform="GOOGLE",
            parent_account_id=parent_account_id,
            account_id=account_id,
            metrics=json.dumps(metrics, indent=2),
            targeting_state=targeting_summary,
            untargeted_ranges=untargeted_summary,
            product_context=product_context,
            all_age_ranges=", ".join(ALL_AGE_RANGES),
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
        """Parse and validate LLM response."""
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()

        parsed = OptimizationResponse.model_validate_json(content)
        for rec in parsed.recommendations:
            rec.campaign_type = "SEARCH"
        return list(parsed.recommendations)

    def _build_targeting_summary(
        self, metrics: list, targeting_map: dict[str, set[str]]
    ) -> str:
        """Build a summary of current targeting state for the LLM prompt."""
        ad_groups = {}
        for m in metrics:
            ad_group_id = str(m.get("adGroup", {}).get("id", ""))
            ad_group_name = m.get("adGroup", {}).get("name", "Unknown")
            if ad_group_id and ad_group_id not in ad_groups:
                ad_groups[ad_group_id] = ad_group_name

        summary_lines = []
        for ad_group_id, ad_group_name in ad_groups.items():
            targeted = targeting_map.get(ad_group_id, set())
            if targeted:
                summary_lines.append(
                    f"- Ad Group {ad_group_id} ({ad_group_name}): {', '.join(sorted(targeted))}"
                )
            else:
                summary_lines.append(
                    f"- Ad Group {ad_group_id} ({ad_group_name}): No age targeting configured"
                )

        return "\n".join(summary_lines) if summary_lines else "No ad groups found"

    def _build_untargeted_summary(
        self, metrics: list, targeting_map: dict[str, set[str]]
    ) -> str:
        """Build a summary of untargeted age ranges available for testing."""
        ad_groups = {}
        for m in metrics:
            ad_group_id = str(m.get("adGroup", {}).get("id", ""))
            ad_group_name = m.get("adGroup", {}).get("name", "Unknown")
            if ad_group_id and ad_group_id not in ad_groups:
                ad_groups[ad_group_id] = ad_group_name

        summary_lines = []
        for ad_group_id, ad_group_name in ad_groups.items():
            targeted = targeting_map.get(ad_group_id, set())
            # Exclude UNDETERMINED — it is not a real targetable range
            untargeted = set(ALL_AGE_RANGES) - targeted - {"AGE_RANGE_UNDETERMINED"}
            if untargeted:
                summary_lines.append(
                    f"- Ad Group {ad_group_id} ({ad_group_name}): {', '.join(sorted(untargeted))}"
                )
            else:
                summary_lines.append(
                    f"- Ad Group {ad_group_id} ({ad_group_name}): All age ranges already targeted"
                )

        return "\n".join(summary_lines) if summary_lines else "No ad groups found"

    def _build_product_context(self, metrics: list) -> str:
        """Build product context for LLM to understand the business."""
        products = {}
        for m in metrics:
            product_id = m.get("product_id", "")
            product_summary = m.get("product_summary", "")
            if product_id and product_summary and product_id not in products:
                products[product_id] = product_summary

        if not products:
            return "No product information available"

        context_lines = []
        for product_id, summary in products.items():
            context_lines.append(f"Product {product_id}: {summary}")

        return "\n".join(context_lines)

    def _filter_recommendations(
        self,
        recommendations: list[CampaignRecommendation],
        targeting_map: dict[str, set[str]],
    ) -> list[CampaignRecommendation]:
        """
        Filter LLM recommendations based on current targeting state.

        Rules:
        - ADD only if the age range is NOT currently targeted
        - REMOVE only if the age range IS currently targeted
        - Deduplicate by (ad_group_id, age_range, recommendation)
        - All-REMOVE guard: skip ad group if removes would zero out all targeting
        - AGE_RANGE_UNDETERMINED is excluded from targeting checks
        """
        filtered_recs = []

        for rec in recommendations:
            if not rec.fields.age:
                continue

            ad_group_id = rec.fields.age[0].ad_group_id
            if not ad_group_id:
                continue

            # Exclude UNDETERMINED — not a real targetable range
            currently_targeted = {
                r
                for r in targeting_map.get(ad_group_id, set())
                if r != "AGE_RANGE_UNDETERMINED"
            }

            # Log what LLM suggested
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
