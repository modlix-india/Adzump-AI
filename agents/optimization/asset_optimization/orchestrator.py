import structlog
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.assets import GoogleAssetsAdapter
from core.models.optimization import (
    AssetFieldRecommendation,
    CampaignRecommendation,
    OptimizationFields,
)
from core.services.campaign_mapping import campaign_mapping_service
from .categorizer import AssetCategorizer
from .similarity_matcher import SimilarityMatcher
from .suggestion_generator import SuggestionGenerator

logger = structlog.get_logger(__name__)


class AssetOptimizationOrchestrator:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.assets_adapter = GoogleAssetsAdapter()
        self.categorizer = AssetCategorizer()
        self.matcher = SimilarityMatcher()
        self.generator = SuggestionGenerator()

    async def analyze_all_campaigns(self, client_code: str) -> dict:
        """Analyze all campaigns across all accessible accounts for a client_code."""
        logger.info(
            "Starting bulk campaign analysis for all accounts",
            client_code=client_code,
            step="bulk_analysis_start",
        )

        # Step 1: Fetch all accessible accounts (expands MCC to sub-accounts)
        try:
            all_accounts = await self.accounts_adapter.fetch_accessible_accounts(
                client_code
            )
            logger.info(
                "Accounts fetched",
                step="accounts_fetched",
                total_accounts=len(all_accounts),
            )
        except Exception as e:
            logger.error(
                "Failed to fetch accessible accounts",
                client_code=client_code,
                error=str(e),
            )
            raise

        if not all_accounts:
            return {
                "client_code": client_code,
                "total_accounts": 0,
                "total_campaigns": 0,
                "successful_campaigns": 0,
                "failed_campaigns": 0,
                "results": [],
                "summary": {"total_low_assets": 0, "total_suggestions": 0},
                "message": "No accessible accounts found for this client",
            }

        # Step 2: Process each account (fetch campaigns)
        all_results = []
        total_campaigns_processed = 0
        successful_count = 0
        failed_count = 0
        total_low_assets = 0
        total_suggestions = 0

        for account in all_accounts:
            customer_id = account["customer_id"]
            login_customer_id = account["login_customer_id"]

            try:
                # Fetch campaigns for this account
                campaigns = await self.assets_adapter.fetch_all_campaigns(
                    customer_id=customer_id,
                    login_customer_id=login_customer_id,
                    client_code=client_code,
                )

                logger.info(
                    "Campaigns fetched for account",
                    customer_id=customer_id,
                    campaigns_count=len(campaigns),
                )

                # Step 3: Analyze each campaign
                for campaign in campaigns:
                    total_campaigns_processed += 1
                    campaign_id = campaign["id"]

                    try:
                        result = await self.analyze_campaign(
                            customer_id=customer_id,
                            campaign_id=campaign_id,
                            login_customer_id=login_customer_id,
                            client_code=client_code,
                        )

                        # Add customer context to result
                        result["customer_id"] = customer_id
                        result["login_customer_id"] = login_customer_id
                        result["status"] = "success"
                        result["error"] = None

                        all_results.append(result)
                        successful_count += 1
                        total_low_assets += result.get("total_low_assets", 0)
                        total_suggestions += result.get("total_suggestions", 0)

                        logger.info(
                            "Campaign analysis succeeded",
                            customer_id=customer_id,
                            campaign_id=campaign_id,
                            suggestions_count=result.get("total_suggestions", 0),
                        )

                    except Exception as e:
                        # Log and continue on campaign failure
                        logger.error(
                            "Campaign analysis failed",
                            customer_id=customer_id,
                            campaign_id=campaign_id,
                            error=str(e),
                        )
                        failed_count += 1
                        all_results.append(
                            {
                                "customer_id": customer_id,
                                "campaign_id": campaign_id,
                                "campaign_name": campaign.get("name", ""),
                                "total_low_assets": 0,
                                "total_suggestions": 0,
                                "suggestions": [],
                                "status": "error",
                                "error": str(e),
                            }
                        )

            except Exception as e:
                # Log and continue on account-level failure
                logger.error(
                    "Failed to process account",
                    customer_id=customer_id,
                    error=str(e),
                )
                # Don't increment failed_count here - we don't know how many campaigns failed

        # Step 4: Transform to Pydantic models (following age optimization pattern)
        campaign_product_map = (
            await campaign_mapping_service.get_campaign_product_mapping(client_code)
        )
        all_recommendations = []

        for result in all_results:
            if result.get("status") == "error" or not result.get("suggestions"):
                continue  # Skip failed campaigns or campaigns with no suggestions

            customer_id = result["customer_id"]
            login_customer_id = result.get("login_customer_id", customer_id)
            campaign_id = result["campaign_id"]
            product_id = campaign_product_map.get(campaign_id, "")
            campaign_type = result.get("campaign_type", "SEARCH")

            # Transform suggestions to AssetFieldRecommendation
            asset_recommendations = []
            for sugg in result["suggestions"]:
                asset_recommendations.append(
                    AssetFieldRecommendation(
                        ad_group_id=sugg["ad_group_id"],
                        ad_group_name=sugg.get(
                            "ad_group_name", f"AdGroup {sugg['ad_group_id']}"
                        ),
                        ad_id=sugg.get("ad_id", ""),
                        ad_name=sugg.get("ad_name", ""),
                        # TODO: Fetch from Google Ads API
                        ad_group_ad_asset_resource_name=sugg.get(
                            "resource_name",
                            f"customers/{customer_id}/adGroupAdAssets/{sugg['ad_group_id']}~0~{sugg.get('id', '0')}",
                        ),
                        asset_id=sugg.get("id"),
                        asset_type=sugg["type"],
                        text=sugg["text"],
                        recommendation="REMOVE" if sugg["label"] == "remove" else "ADD",
                        reason=sugg["reason"],
                        applied=False,
                    )
                )

            # Create CampaignRecommendation
            recommendation = CampaignRecommendation(
                platform="google_ads",
                parent_account_id=login_customer_id,
                account_id=customer_id,
                product_id=product_id,
                campaign_id=campaign_id,
                campaign_name=result["campaign_name"],
                campaign_type=campaign_type,
                completed=False,
                fields=OptimizationFields(assets=asset_recommendations),
            )
            all_recommendations.append(recommendation)

        logger.info(
            "Bulk campaign analysis completed",
            step="bulk_analysis_complete",
            total_campaigns=total_campaigns_processed,
            successful=successful_count,
            failed=failed_count,
            recommendations_count=len(all_recommendations),
        )

        # Return in standard format (matching age optimization)
        return {"recommendations": [r.model_dump() for r in all_recommendations]}

    async def analyze_campaign(
        self,
        customer_id: str,
        campaign_id: str,
        login_customer_id: str,
        client_code: str,
    ) -> dict:
        logger.info(
            "Starting campaign analysis",
            customer_id=customer_id,
            campaign_id=campaign_id,
        )

        # Step 1: Fetch performance data using adapter
        logger.info("Fetching asset performance data", step="fetch_performance")
        performance_data = await self.assets_adapter.fetch_asset_performance(
            customer_id=customer_id,
            campaign_id=campaign_id,
            login_customer_id=login_customer_id,
            client_code=client_code,
        )
        logger.info(
            "Performance data fetched",
            step="fetch_performance_complete",
            total_results=len(performance_data),
        )

        if not performance_data:
            return {
                "campaign_id": campaign_id,
                "campaign_name": "",
                "campaign_type": "SEARCH",
                "total_low_assets": 0,
                "suggestions": [],
                "message": "No asset performance data found for this campaign",
            }

        # Extract campaign_type from first result (all same campaign)
        campaign_type = (
            performance_data[0]
            .get("campaign", {})
            .get("advertisingChannelType", "SEARCH")
        )

        # Step 2: Extract asset IDs and fetch text using adapter
        asset_ids = list(
            set(
                [
                    item.get("adGroupAdAssetView", {}).get("asset", "").split("/")[-1]
                    for item in performance_data
                ]
            )
        )

        logger.info(
            "Fetching asset text", step="fetch_asset_text", asset_count=len(asset_ids)
        )
        asset_details = await self.assets_adapter.fetch_asset_text(
            asset_ids=asset_ids,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            client_code=client_code,
        )
        logger.info(
            "Asset text fetched",
            step="fetch_asset_text_complete",
            assets_retrieved=len(asset_details),
        )

        # Step 3: Categorize assets into tiers using categorizer module
        logger.info("Categorizing assets", step="categorize_assets")
        categorized = self.categorizer.categorize_assets(
            performance_data, asset_details
        )
        logger.info(
            "Assets categorized",
            step="categorize_complete",
            low_count=len(categorized["low_assets"]),
            tier_1_count=len(categorized["tier_1"]),
            tier_2_count=len(categorized["tier_2"]),
            tier_3_count=len(categorized["tier_3"]),
        )

        if not categorized["low_assets"]:
            return {
                "campaign_id": campaign_id,
                "campaign_name": performance_data[0]
                .get("campaign", {})
                .get("name", ""),
                "total_low_assets": 0,
                "suggestions": [],
                "message": "Great news! All assets are performing well. No optimizations needed.",
                "status": "optimized",
            }

        logger.info(
            "Found assets",
            low=len(categorized["low_assets"]),
            tier_1=len(categorized["tier_1"]),
            tier_2=len(categorized["tier_2"]),
            tier_3=len(categorized["tier_3"]),
        )

        # Step 4: Generate suggestions for each LOW asset
        suggestions = []

        for idx, low_asset in enumerate(categorized["low_assets"], 1):
            try:
                logger.info(
                    "Processing LOW asset",
                    step="process_low_asset",
                    progress=f"{idx}/{len(categorized['low_assets'])}",
                    asset_id=low_asset["asset_id"],
                    asset_type=low_asset["asset_type"],
                    text=low_asset["text"][:50] + "..."
                    if len(low_asset["text"]) > 50
                    else low_asset["text"],
                )

                # Find similar assets with fallback using matcher module
                similar_assets, source_tier = await self.matcher.find_similar_assets(
                    low_asset["text"],
                    categorized,
                    low_asset["asset_type"],
                    low_asset["campaign_name"],
                    low_asset["ad_group_name"],
                )
                logger.info(
                    "Similar assets found",
                    step="find_similar_complete",
                    asset_id=low_asset["asset_id"],
                    similar_count=len(similar_assets),
                    source_tier=source_tier,
                )

                # Generate suggestions using generator module
                logger.info(
                    "Generating suggestions",
                    step="generate_suggestions",
                    asset_id=low_asset["asset_id"],
                )
                new_options = await self.generator.generate_suggestions(
                    low_asset,
                    similar_assets,
                    source_tier,
                    low_asset["campaign_name"],
                    low_asset["ad_group_name"],
                )
                logger.info(
                    "Suggestions generated",
                    step="generate_suggestions_complete",
                    asset_id=low_asset["asset_id"],
                    raw_count=len(new_options),
                )

                # Validate using generator module
                logger.info(
                    "Validating suggestions",
                    step="validate_suggestions",
                    asset_id=low_asset["asset_id"],
                )
                validated_options = self.generator.validate_suggestions(
                    new_options, low_asset["asset_type"]
                )
                logger.info(
                    "Suggestions validated",
                    step="validate_complete",
                    asset_id=low_asset["asset_id"],
                    validated_count=len(validated_options),
                    rejected_count=len(new_options) - len(validated_options),
                )

                if validated_options:
                    # Add the "remove" item for the LOW asset
                    suggestions.append(
                        {
                            "id": low_asset["asset_id"],
                            "type": low_asset["asset_type"],
                            "text": low_asset["text"],
                            "label": "remove",
                            "reason": f"LOW performance ({low_asset['impressions']} impressions)",
                            "ad_group_id": low_asset["ad_group_id"],
                            "ad_id": low_asset.get("ad_id", ""),
                            "campaign_id": campaign_id,
                            "performance_label": low_asset["label"],
                            "impressions": low_asset["impressions"],
                            "based_on": source_tier,
                        }
                    )

                    # Add only the BEST validated option (1:1 replacement)
                    best_option = validated_options[0]
                    suggestions.append(
                        {
                            "id": None,  # New asset, no ID yet
                            "type": low_asset["asset_type"],
                            "text": best_option["text"],
                            "label": "add",
                            "reason": f"Replacement for LOW asset (generated from {source_tier})",
                            "ad_group_id": low_asset["ad_group_id"],
                            "ad_id": low_asset.get("ad_id", ""),
                            "campaign_id": campaign_id,
                            "character_count": best_option["character_count"],
                            "replaces_asset_id": low_asset["asset_id"],
                            "based_on": source_tier,
                        }
                    )

            except Exception as e:
                logger.error(
                    "Failed to generate suggestions for asset",
                    asset_id=low_asset["asset_id"],
                    error=str(e),
                )

        result = {
            "campaign_id": campaign_id,
            "campaign_name": categorized["low_assets"][0]["campaign_name"]
            if categorized["low_assets"]
            else "",
            "campaign_type": campaign_type,
            "total_low_assets": len(categorized["low_assets"]),
            "total_suggestions": len(suggestions),
            "suggestions": suggestions,
        }

        logger.info(
            "Campaign analysis completed",
            step="analysis_complete",
            total_low_assets=result["total_low_assets"],
            total_suggestions=result["total_suggestions"],
            suggestions_per_asset=round(
                result["total_suggestions"] / result["total_low_assets"], 1
            )
            if result["total_low_assets"] > 0
            else 0,
        )

        return result
