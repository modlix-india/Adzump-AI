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
from services.description_generator import DescriptionGenerator

logger = structlog.get_logger(__name__)


class DescriptionOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.assets_adapter = GoogleAssetsAdapter()
        self.categorizer = AssetCategorizer()
        self.matcher = SimilarityMatcher()
        self.generator = DescriptionGenerator()
        self.validator = AssetValidator()

    async def generate_recommendations(self, client_code: str) -> dict:
        """Generate description optimization recommendations for all accessible accounts."""
        logger.info("Generating description recommendations", client_code=client_code)

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
        # Debug: list keys if count is low
        if len(campaign_product_map) < 5:
            logger.debug("Linked campaign IDs", ids=list(campaign_product_map.keys()))

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
        """Process a single Google Ads account."""
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        logger.info(
            "Processing account hierarchy",
            mcc_id=parent_account_id,
            account_id=account_id,
        )

        # Fetch all campaigns for this account
        campaigns = await self.assets_adapter.fetch_all_campaigns(
            customer_id=account_id,
            login_customer_id=parent_account_id,
            client_code=client_code,
        )

        if not campaigns:
            logger.info("No campaigns found for account", account_id=account_id)
            return []

        # Process each campaign
        results = []
        for campaign in campaigns:
            campaign_id_str = str(campaign["id"]).strip()
            is_linked = campaign_id_str in campaign_product_map

            logger.info(
                f"Campaign Linking Status: {campaign['name']} ({campaign['id']})",
                client_code=client_code,
                is_linked=is_linked,
            )

            if not is_linked:
                continue

            try:
                rec = await self._analyze_campaign(
                    customer_id=account_id,
                    campaign_id=campaign["id"],
                    campaign_name=campaign["name"],
                    login_customer_id=parent_account_id,
                    product_id=campaign_product_map.get(campaign_id_str, ""),
                    client_code=client_code,
                )
                if rec:
                    results.append(rec)
            except Exception as e:
                logger.error(
                    "Failed to analyze campaign",
                    campaign_id=campaign["id"],
                    error=str(e),
                )

        if not results and not any(
            str(c["id"]).strip() in campaign_product_map for c in campaigns
        ):
            logger.info(
                "No linked campaigns for account",
                account_id=account_id,
                total_campaigns=len(campaigns),
            )

        return results

    async def _analyze_campaign(
        self,
        customer_id: str,
        campaign_id: str,
        campaign_name: str,
        login_customer_id: str,
        product_id: str,
        client_code: str,
    ) -> CampaignRecommendation | None:
        """Analyze a single campaign for description optimization opportunities."""
        # Fetch asset performance data
        performance_data = await self.assets_adapter.fetch_asset_performance(
            customer_id=customer_id,
            campaign_id=campaign_id,
            login_customer_id=login_customer_id,
            client_code=client_code,
        )

        if not performance_data:
            return None

        # Extract asset IDs and fetch text
        asset_ids = list(
            set(
                [
                    item.get("adGroupAdAssetView", {}).get("asset", "").split("/")[-1]
                    for item in performance_data
                ]
            )
        )

        asset_details = await self.assets_adapter.fetch_asset_text(
            asset_ids=asset_ids,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            client_code=client_code,
        )

        # Categorize assets (DESCRIPTIONS only)
        categorized = self.categorizer.categorize_assets(
            performance_data, asset_details, asset_type="DESCRIPTION"
        )

        logger.info(
            "Descriptions categorized",
            campaign_id=campaign_id,
            low=len(categorized["low_assets"]),
            tier_1=len(categorized["tier_1"]),
        )

        if not categorized["low_assets"]:
            logger.info("No low-performing descriptions found", campaign_id=campaign_id)
            return None

        # Generate recommendations for each low-performing description
        description_recommendations = []
        for low_asset in categorized["low_assets"]:
            try:
                # Find similar descriptions
                similar_assets, source_tier = await self.matcher.find_similar_assets(
                    low_asset["text"],
                    categorized,
                    asset_type="DESCRIPTION",
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
                    new_options, "DESCRIPTION"
                )

                if validated_options:
                    # Add REMOVE recommendation for low-performing description
                    description_recommendations.append(
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
                    description_recommendations.append(
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
                            reason=f"Replacement for LOW description (generated from {source_tier})",
                            applied=False,
                        )
                    )

            except Exception as e:
                logger.error(
                    "Failed to generate description recommendations",
                    asset_id=low_asset["asset_id"],
                    error=str(e),
                )

        if not description_recommendations:
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
            fields=OptimizationFields(descriptions=description_recommendations),
        )


description_optimization_agent = DescriptionOptimizationAgent()
