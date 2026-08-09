import asyncio
import json
from typing import Optional
from collections import defaultdict
from structlog import get_logger

from adapters.meta.accounts import MetaAccountsAdapter
from adapters.meta.age import MetaAgeAdapter
from core.models.meta_optimization import (
    MetaCampaignRecommendation,
    MetaOptimizationFields,
    MetaAgeFieldRecommendation,
    MetaOptimizationResponse,
    MetaAgeAIResponse,
    AdsetAnalysisResult,
)
from core.services.campaign_mapping import campaign_mapping_service
from core.services.recommendation_storage import recommendation_storage_service
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from core.infrastructure.context import auth_context
from exceptions.custom_exceptions import StorageException


logger = get_logger(__name__)


class MetaAgeOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = MetaAccountsAdapter()
        self.age_adapter = MetaAgeAdapter()

    async def generate_recommendations(self) -> MetaOptimizationResponse:
        client_code = auth_context.client_code
        logger.info("Client code", client_code=client_code)

        all_errors = []

        # Load Meta prompt once for the entire execution
        prompt = load_prompt("meta/meta_age_optimization_prompt.txt")

        # 1. Fetch businesses dynamically
        try:
            businesses = await self.accounts_adapter.list_business_accounts(client_code)
        except Exception as e:
            error_detail = (
                e.error_data if hasattr(e, "error_data") else {"message": str(e)}
            )
            logger.error("Business account fetch failed", error=error_detail)
            return MetaOptimizationResponse(
                success=False,
                message=f"Meta Authentication Failed: {error_detail.get('message', str(e))}",
                errors=[error_detail],
            )

        if not businesses:
            logger.warning("No business accounts found", client_code=client_code)
            return MetaOptimizationResponse(
                success=True,
                message="No business accounts found for this client.",
                recommendations=[],
                errors=[],
            )

        # 2. Fetch ad accounts for all businesses
        account_fetch_tasks = [
            self.accounts_adapter.list_ad_accounts(business["id"], client_code)
            for business in businesses
        ]
        account_fetch_results = await asyncio.gather(
            *account_fetch_tasks, return_exceptions=True
        )

        all_accounts = []
        # Map ad_account_id -> parent_business_id for later use
        account_to_business_map = {}

        for index, ad_account_list in enumerate(account_fetch_results):
            business_id = businesses[index]["id"]
            if isinstance(ad_account_list, Exception):
                error_detail = (
                    ad_account_list.error_data
                    if hasattr(ad_account_list, "error_data")
                    else {"message": str(ad_account_list)}
                )
                logger.error(
                    "Failed to list accounts for business",
                    business_id=business_id,
                    error=error_detail,
                )
                all_errors.append({"business_id": business_id, "error": error_detail})
                continue

            for ad_account in ad_account_list:
                ad_account_id = ad_account["id"]
                account_to_business_map[ad_account_id] = business_id
                all_accounts.append(ad_account)

        if not all_accounts:
            return MetaOptimizationResponse(
                success=True,
                message="No ad accounts found for this client.",
                recommendations=[],
                errors=all_errors,
            )

        campaign_product_map = (
            await campaign_mapping_service.get_campaign_mapping_with_summary(
                client_code
            )
        )

        # DEBUG LOG: Verify storage data
        logger.info(
            "Storage Mapping Status",
            client_code=client_code,
            map_size=len(campaign_product_map),
            sample_ids=list(campaign_product_map.keys())[:5],
        )

        # 3. Process recommendations per account
        results = await asyncio.gather(
            *[
                self._process_account_recommendations(
                    account=account,
                    campaign_product_map=campaign_product_map,
                    client_code=client_code,
                    prompt=prompt,
                )
                for account in all_accounts
            ],
            return_exceptions=True,
        )

        all_adset_recs = []
        for account_result in results:
            if isinstance(account_result, Exception):
                error_detail = (
                    account_result.error_data
                    if hasattr(account_result, "error_data")
                    else {"message": str(account_result)}
                )
                logger.error(
                    "Account recommendation processing failed", error=error_detail
                )
                all_errors.append({"error": error_detail})
                continue

            # Each account_result is now {"recommendations": [...], "errors": [...]}
            all_adset_recs.extend(account_result.get("recommendations", []))
            all_errors.extend(account_result.get("errors", []))

        # Also check for errors inside _process_account_recommendations (handled via gather)

        # Group by campaign_id to form CampaignRecommendation objects
        campaign_groups = defaultdict(list)
        campaign_metadata = {}

        for result in all_adset_recs:
            if not isinstance(result, AdsetAnalysisResult):
                continue

            campaign_groups[result.campaign_id].append(
                MetaAgeFieldRecommendation(
                    adset_id=result.adset_id,
                    adset_name=result.adset_name,
                    current_min=result.current_min,
                    current_max=result.current_max,
                    recommended_min=result.recommended_min,
                    recommended_max=result.recommended_max,
                    reason=result.reason,
                )
            )

            if result.campaign_id not in campaign_metadata:
                campaign_metadata[result.campaign_id] = {
                    "name": result.campaign_name,
                    "objective": result.campaign_objective,
                    "account_id": result.account_id,
                    "product_id": result.product_id,
                }

        final_recommendations: list[MetaCampaignRecommendation] = []
        for campaign_id, age_recs in campaign_groups.items():
            metadata = campaign_metadata[campaign_id]

            parent_business_id = account_to_business_map.get(
                metadata["account_id"], "Unknown"
            )

            final_recommendations.append(
                MetaCampaignRecommendation(
                    platform="META",
                    parent_account_id=parent_business_id,
                    account_id=metadata["account_id"],
                    product_id=metadata["product_id"],
                    campaign_id=campaign_id,
                    campaign_name=metadata["name"],
                    campaign_type=metadata["objective"],
                    fields=MetaOptimizationFields(age=age_recs),
                )
            )

        # Store recommendations — mirrors Google agent pattern
        try:
            await asyncio.gather(
                *[
                    recommendation_storage_service.store(rec, client_code)
                    for rec in final_recommendations
                ]
            )
        except StorageException as e:
            logger.error("meta_age_storage_failed", error=str(e))
            return MetaOptimizationResponse(
                success=False,
                message=f"Recommendations generated but storage failed: {str(e)}",
                recommendations=[],
                errors=[{"message": str(e)}],
            )

        response_obj = MetaOptimizationResponse(
            success=True,
            message="Meta age optimization recommendations generated.",
            recommendations=final_recommendations,
            errors=all_errors,
        )

        return response_obj

    # ACCOUNT PROCESSING
    async def _process_account_recommendations(
        self,
        account: dict,
        campaign_product_map: dict,
        client_code: str,
        prompt: str,
    ) -> dict:  # Returns {"recommendations": [], "errors": []}
        ad_account_id = account.get("id")
        account_errors = []

        try:
            metrics = await self.age_adapter.fetch_age_metrics(
                ad_account_id, client_code
            )
        except Exception as e:
            error_detail = (
                e.error_data if hasattr(e, "error_data") else {"message": str(e)}
            )
            return {
                "recommendations": [],
                "errors": [{"account_id": ad_account_id, "error": error_detail}],
            }

        if not metrics:
            return {"recommendations": [], "errors": []}

        linked_metrics = self._filter_campaigns_by_mapping(
            metrics, campaign_product_map
        )
        if not linked_metrics:
            logger.info("No linked campaigns", ad_account_id=ad_account_id)
            return {"recommendations": [], "errors": []}

        # Group by adset_id
        grouped = defaultdict(list)
        for row in linked_metrics:
            grouped[row["adset_id"]].append(row)

        # Analyze each adset
        tasks = [
            self._analyze_adset_performance(rows, ad_account_id, prompt)
            for rows in grouped.values()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_recommendations = []

        for result in results:
            if isinstance(result, Exception):
                error_detail = (
                    result.error_data
                    if hasattr(result, "error_data")
                    else {"message": str(result)}
                )
                logger.error("Adset analysis failed", error=error_detail)
                account_errors.append(
                    {"account_id": ad_account_id, "error": error_detail}
                )
                continue

            if result and self._is_valid_recommendation(result):
                final_recommendations.append(result)

        return {"recommendations": final_recommendations, "errors": account_errors}

    # FILTER CAMPAIGNS
    def _filter_campaigns_by_mapping(
        self, metrics: list, campaign_product_map: dict
    ) -> list:

        linked = []

        for metric in metrics:
            campaign_id = str(metric.get("campaign_id", ""))

            if campaign_id in campaign_product_map:
                mapping_data = campaign_product_map[campaign_id]

                metric["product_id"] = mapping_data.get("product_id", "")
                metric["product_summary"] = mapping_data.get("summary", "")
                linked.append(metric)

        return linked

    # ANALYZE PER ADSET
    async def _analyze_adset_performance(
        self, rows: list[dict], ad_account_id: str, prompt: str
    ) -> Optional[AdsetAnalysisResult]:

        first = rows[0]

        product_context = first.get("product_summary", "No product info")

        current_min = first.get("current_min", 18)
        current_max = first.get("current_max", 65)

        # Step 1: Prepare clean metrics for LLM
        cleaned_metrics = self._format_metrics_for_llm(rows)
        if not cleaned_metrics:
            return None

        formatted = prompt.format(
            account_id=ad_account_id,
            metrics=json.dumps(cleaned_metrics, indent=2),
            product_context=product_context,
            current_min=current_min,
            current_max=current_max,
        )

        # Step 2: LLM call
        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are a Meta Ads analyst."},
                {"role": "user", "content": formatted},
            ],
            model="gpt-4o-mini",
        )

        raw_content = response.choices[0].message.content.strip()

        # Step 3: Direct Type-safe Validation using Model
        try:
            parsed_ai = MetaAgeAIResponse.model_validate_json(raw_content)
        except Exception as e:
            logger.error(
                "AI response validation failed",
                error=str(e),
                raw_content=raw_content,
            )
            return None

        # Extract objective safely
        campaign_obj = first.get("objective")

        return AdsetAnalysisResult(
            account_id=ad_account_id,
            campaign_id=first.get("campaign_id"),
            campaign_name=first.get("campaign_name"),
            campaign_objective=campaign_obj,
            product_id=first.get("product_id"),
            adset_id=first.get("adset_id"),
            adset_name=first.get("adset_name"),
            current_min=current_min,
            current_max=current_max,
            recommended_min=parsed_ai.recommended_age_min,
            recommended_max=parsed_ai.recommended_age_max,
            reason=parsed_ai.reason,
        )

    # METRIC PREPARATION
    def _format_metrics_for_llm(self, rows: list[dict]) -> list[dict]:
        cleaned = []

        for row in rows:
            try:
                # Extract strategic indicators (CPA, ROAS, Frequency, etc.)
                indicators = self._extract_performance_indicators(row)
                cleaned.append(indicators)
            except Exception as e:
                logger.warning("Failed to clean metric row", error=str(e), row=row)
                continue

        return cleaned

    def _extract_performance_indicators(self, row: dict) -> dict:

        spend = float(row.get("spend") or 0)
        return {
            "age": row.get("age"),
            "unique_ctr": float(row.get("unique_ctr") or 0),
            "frequency": round(float(row.get("frequency") or 0), 2),
            "spend": spend,
            "cpc": float(row.get("cpc") or 0),
            "cpm": float(row.get("cpm") or 0),
            "reach": int(row.get("reach") or 0),
            "impressions": int(row.get("impressions") or 0),
        }

    # VALIDATION
    def _is_valid_recommendation(self, recommendation: AdsetAnalysisResult) -> bool:
        if not recommendation:
            return False

        if recommendation.recommended_min >= recommendation.recommended_max:
            return False

        if (
            recommendation.recommended_min == recommendation.current_min
            and recommendation.recommended_max == recommendation.current_max
        ):
            return False

        return True


meta_age_optimization_agent = MetaAgeOptimizationAgent()
