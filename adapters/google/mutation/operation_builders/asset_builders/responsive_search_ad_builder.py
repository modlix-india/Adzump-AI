import structlog
from typing import List, Dict, Any, Union
from core.models.optimization import HeadlineRecommendation, DescriptionRecommendation
from exceptions.custom_exceptions import GoogleAdsMutationError
from adapters.google.client import GoogleAdsClient
from adapters.google.mutation.mutation_config import CONFIG
from adapters.google.mutation.mutation_validator import MutationValidator
from adapters.google.mutation.mutation_context import MutationContext
from adapters.google.mutation import utils

logger = structlog.get_logger(__name__)

RSARecommendation = Union[HeadlineRecommendation, DescriptionRecommendation]


class ResponsiveSearchAdBuilder:
    def __init__(self):
        self.client = GoogleAdsClient()
        self.validator = MutationValidator()

    async def build_headlines_ops(
        self,
        recommendations: List[HeadlineRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        return await self._build_ops(
            recommendations=recommendations,
            context=context,
            asset_type="headlines",
            max_length=CONFIG.HEADLINES.MAX_LENGTH,
            min_qty=CONFIG.HEADLINES.MIN_COUNT,
            max_qty=CONFIG.HEADLINES.MAX_COUNT,
        )

    async def build_descriptions_ops(
        self,
        recommendations: List[DescriptionRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        return await self._build_ops(
            recommendations=recommendations,
            context=context,
            asset_type="descriptions",
            max_length=CONFIG.DESCRIPTIONS.MAX_LENGTH,
            min_qty=CONFIG.DESCRIPTIONS.MIN_COUNT,
            max_qty=CONFIG.DESCRIPTIONS.MAX_COUNT,
        )

    async def _build_ops(
        self,
        recommendations: List[RSARecommendation],
        context: MutationContext,
        asset_type: str,
        max_length: int,
        min_qty: int,
        max_qty: int,
    ) -> List[Dict[str, Any]]:
        ad_updates = self._group_by_ad(recommendations, max_length, asset_type)
        operations = []

        for ad_id, changes in ad_updates.items():
            try:
                op = await self._build_single_ad_op(
                    context=context,
                    ad_id=ad_id,
                    changes=changes,
                    asset_type=asset_type,
                    min_qty=min_qty,
                    max_qty=max_qty,
                )
                if op:
                    operations.append(op)
            except GoogleAdsMutationError as e:
                logger.error("Skippable error during build", ad=ad_id, error=e.message)
            except Exception:
                logger.error("Fatal error during build", ad=ad_id, exc_info=True)
                raise

        return operations

    def _group_by_ad(
        self,
        recommendations: List[RSARecommendation],
        max_length: int,
        asset_type: str,
    ) -> Dict[str, Dict[str, List]]:
        """Validate and group recommendations by ad_id."""
        ad_updates: Dict[str, Dict[str, List]] = {}
        for item in recommendations:
            if not self.validator.validate_text_length(
                item.text, max_length, asset_type
            ):
                continue
            changes = ad_updates.setdefault(item.ad_id, {"add": [], "remove": []})
            key = "add" if item.recommendation == "ADD" else "remove"
            changes[key].append(item)
        return ad_updates

    async def _build_single_ad_op(
        self,
        context: MutationContext,
        ad_id: str,
        changes: Dict[str, List],
        asset_type: str,
        min_qty: int,
        max_qty: int,
    ) -> Dict[str, Any] | None:
        """Fetch existing ad, merge assets, and build a single RSA update operation."""
        ad_data = await self._fetch_existing_ad(
            customer_id=context.account_id,
            ad_id=ad_id,
            login_id=context.parent_account_id,
            client_code=context.client_code,
        )
        rsa = ad_data.get("responsiveSearchAd", {})

        merged_assets = utils.merge_text_assets(
            current_assets=self._sanitize(assets=rsa.get(asset_type, [])),
            recommendations_to_add=changes["add"],
            recommendations_to_remove=changes["remove"],
        )

        if len(merged_assets) < min_qty:
            logger.error("Insufficient assets after merge", ad=ad_id, type=asset_type)
            return None

        merged_assets = merged_assets[:max_qty]

        for url in ad_data.get("finalUrls", []):
            self.validator.validate_url(url, "Final URL")

        # RSA updates require both headlines and descriptions;
        # the untouched type is preserved from the existing ad.
        other_type = "descriptions" if asset_type == "headlines" else "headlines"
        asset_fields = {
            asset_type: merged_assets,
            other_type: self._sanitize(assets=rsa.get(other_type, [])),
        }

        return utils.build_rsa_update_operation(
            customer_id=context.account_id,
            ad_group_id=ad_data.get("adGroupId"),
            ad_id=ad_id,
            headlines=asset_fields["headlines"],
            descriptions=asset_fields["descriptions"],
            final_urls=ad_data.get("finalUrls", []),
            update_mask_fields=[
                f"ad.responsive_search_ad.{asset_type}",
                "ad.final_urls",
            ],
        )

    async def _fetch_existing_ad(
        self, customer_id: str, ad_id: str, login_customer_id: str, client_code: str
    ) -> Dict[str, Any]:
        query = f"SELECT ad_group_ad.ad_group, ad.id, ad.responsive_search_ad.headlines, ad.responsive_search_ad.descriptions, ad.final_urls FROM ad_group_ad WHERE ad.id = {ad_id} LIMIT 1"
        results = await self.client.search(
            customer_id=customer_id,
            query=query,
            client_code=client_code,
            login_customer_id=login_customer_id,
        )
        if not results:
            raise GoogleAdsMutationError(
                f"Ad {ad_id} not found", details={"ad_id": ad_id}
            )

        result = results[0]
        ad_data = result.get("ad", {})
        ad_group_res = result.get("adGroupAd", {}).get("adGroup", "")
        ad_group_id = ad_group_res.split("/")[-1] if ad_group_res else ""

        ad_data["adGroupId"] = ad_group_id
        return ad_data

    def _sanitize(self, assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {"text": a.get("text"), "pinnedField": a.get("pinnedField")} for a in assets
        ]
