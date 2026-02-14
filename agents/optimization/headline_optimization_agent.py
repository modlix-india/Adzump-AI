import asyncio
import structlog
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.assets import GoogleAssetsAdapter
from core.models.optimization import (
    AssetRecommendation,
    CampaignRecommendation,
    OptimizationFields,
)
from core.services.campaign_mapping import campaign_mapping_service
from core.services.recommendation_storage import recommendation_storage_service
from core.optimization.categorizer import AssetCategorizer
from core.optimization.similarity_matcher import SimilarityMatcher
from core.optimization.validators import AssetValidator
from services.headline_generator import HeadlineGenerator

logger = structlog.get_logger(__name__)


class HeadlineOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.assets_adapter = GoogleAssetsAdapter()
        self.categorizer = AssetCategorizer()
        self.matcher = SimilarityMatcher()
        self.generator = HeadlineGenerator()
        self.validator = AssetValidator()

    async def generate_recommendations(self, client_code: str) -> dict:
        """Generate headline optimization recommendations for all accessible accounts."""
        logger.info("Generating headline recommendations", client_code=client_code)

        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        logger.info(f"Processing {len(accounts)} accounts", client_code=client_code)

        campaign_product_map = (
            await campaign_mapping_service.get_campaign_product_mapping(client_code)
        )
        logger.info(
            "Campaign product mapping fetched",
            client_code=client_code,
            count=len(campaign_product_map),
        )

        results = await asyncio.gather(
            *[
                self._process_account(
                    account=acc,
                    campaign_product_map=campaign_product_map,
                    client_code=client_code,
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

    async def _process_account(
        self,
        account: dict,
        campaign_product_map: dict,
        client_code: str,
    ) -> list[CampaignRecommendation]:
        """Process a single Google Ads account with bulk asset fetching."""
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        logger.info(
            "Processing account hierarchy",
            mcc_id=parent_account_id,
            account_id=account_id,
        )

        # Fetch ALL asset performance data for the account at once
        all_performance_data = await self.assets_adapter.fetch_asset_performance(
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=client_code,
            campaign_id=None,  # Account-level fetch
        )

        if not all_performance_data:
            logger.info("No asset performance data for account", account_id=account_id)
            return []

        # Extract campaigns from performance data and filter for linked ones
        linked_campaigns = {}
        for item in all_performance_data:
            campaign = item.get("campaign", {})
            campaign_id_str = str(campaign.get("id", ""))

            if campaign_id_str in campaign_product_map:
                if campaign_id_str not in linked_campaigns:
                    linked_campaigns[campaign_id_str] = {
                        "id": campaign_id_str,
                        "name": campaign.get("name", ""),
                        "product_id": campaign_product_map[campaign_id_str],
                    }
                    logger.info(
                        f"Campaign Linking Status: {campaign.get('name')} ({campaign_id_str})",
                        client_code=client_code,
                        is_linked=True,
                    )

        if not linked_campaigns:
            logger.info(
                "No linked campaigns for account",
                account_id=account_id,
            )
            return []

        # Extract all unique asset IDs
        all_asset_ids = list(
            set(
                item.get("adGroupAdAssetView", {}).get("asset", "").split("/")[-1]
                for item in all_performance_data
            )
        )

        # Fetch all asset text at once
        all_asset_details = await self.assets_adapter.fetch_asset_text(
            asset_ids=all_asset_ids,
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=client_code,
        )

        # Group performance data by campaign
        campaign_performance = {}
        for item in all_performance_data:
            campaign_id_str = str(item.get("campaign", {}).get("id", ""))
            if campaign_id_str in linked_campaigns:
                if campaign_id_str not in campaign_performance:
                    campaign_performance[campaign_id_str] = []
                campaign_performance[campaign_id_str].append(item)

        # Process each linked campaign with pre-fetched data
        results = []
        for campaign_id_str, campaign_info in linked_campaigns.items():
            performance_data = campaign_performance.get(campaign_id_str, [])
            if not performance_data:
                continue

            try:
                rec = await self._analyze_campaign_with_data(
                    customer_id=account_id,
                    campaign_id=campaign_info["id"],
                    campaign_name=campaign_info["name"],
                    login_customer_id=parent_account_id,
                    product_id=campaign_info["product_id"],
                    performance_data=performance_data,
                    asset_details=all_asset_details,
                    client_code=client_code,
                )
                if rec:
                    results.append(rec)
            except Exception as e:
                logger.error(
                    "Failed to analyze campaign",
                    campaign_id=campaign_info["id"],
                    error=str(e),
                )

        return results

    async def _analyze_campaign_with_data(
        self,
        customer_id: str,
        campaign_id: str,
        campaign_name: str,
        login_customer_id: str,
        product_id: str,
        performance_data: list[dict],
        asset_details: dict[str, str],
        client_code: str,
    ) -> CampaignRecommendation | None:
        """Analyze a campaign with pre-fetched performance and asset data."""

        # Categorize assets (HEADLINES only)
        categorized = self.categorizer.categorize_assets(
            performance_data, asset_details, asset_type="HEADLINE"
        )

        logger.info(
            "Headlines categorized",
            campaign_id=campaign_id,
            low=len(categorized["low_assets"]),
            tier_1=len(categorized["tier_1"]),
        )

        if not categorized["low_assets"]:
            logger.info("No low-performing headlines found", campaign_id=campaign_id)
            return None

        # Generate recommendations for each low-performing headline
        headline_recommendations = []
        for low_asset in categorized["low_assets"]:
            try:
                # Find similar headlines
                similar_assets, source_tier = await self.matcher.find_similar_assets(
                    low_asset["text"],
                    categorized,
                    asset_type="HEADLINE",
                    campaign_name=low_asset["campaign_name"],
                    ad_group_name=low_asset["ad_group_name"],
                )

                # Generate suggestions
                new_options = await self.generator.generate_suggestions(
                    low_asset,
                    similar_assets,
                    source_tier,
                    low_asset["campaign_name"],
                    low_asset["ad_group_name"],
                )

                # Validate
                validated_options = self.validator.validate_suggestions(
                    new_options, "HEADLINE"
                )

                if validated_options:
                    # Add REMOVE recommendation for low-performing headline
                    headline_recommendations.append(
                        AssetRecommendation(
                            ad_group_id=low_asset["ad_group_id"],
                            ad_group_name=low_asset.get(
                                "ad_group_name", f"AdGroup {low_asset['ad_group_id']}"
                            ),
                            ad_id=low_asset.get("ad_id", ""),
                            ad_name=low_asset.get("ad_name", ""),
                            ad_group_ad_asset_resource_name=low_asset.get(
                                "resource_name",
                                f"customers/{customer_id}/adGroupAdAssets/{low_asset['ad_group_id']}~0~{low_asset.get('asset_id', '0')}",
                            ),
                            asset_id=low_asset["asset_id"],
                            text=low_asset["text"],
                            recommendation="REMOVE",
                            reason=f"LOW performance ({low_asset['impressions']} impressions)",
                            applied=False,
                        )
                    )

                    # Add ADD recommendation for best replacement (1:1)
                    best_option = validated_options[0]
                    headline_recommendations.append(
                        AssetRecommendation(
                            ad_group_id=low_asset["ad_group_id"],
                            ad_group_name=low_asset.get(
                                "ad_group_name", f"AdGroup {low_asset['ad_group_id']}"
                            ),
                            ad_id=low_asset.get("ad_id", ""),
                            ad_name=low_asset.get("ad_name", ""),
                            ad_group_ad_asset_resource_name=low_asset.get(
                                "resource_name",
                                f"customers/{customer_id}/adGroupAdAssets/{low_asset['ad_group_id']}~0~0",
                            ),
                            asset_id=None,  # New asset
                            text=best_option["text"],
                            recommendation="ADD",
                            reason=f"Replacement for LOW headline (generated from {source_tier})",
                            applied=False,
                        )
                    )

            except Exception as e:
                logger.error(
                    "Failed to generate headline recommendations",
                    asset_id=low_asset["asset_id"],
                    error=str(e),
                )

        if not headline_recommendations:
            return None

        # Build CampaignRecommendation
        return CampaignRecommendation(
            platform="google_ads",
            parent_account_id=login_customer_id,
            account_id=customer_id,
            product_id=product_id,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            campaign_type="SEARCH",
            completed=False,
            fields=OptimizationFields(headlines=headline_recommendations),
        )


headline_optimization_agent = HeadlineOptimizationAgent()
