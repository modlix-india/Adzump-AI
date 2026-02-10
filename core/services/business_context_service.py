import asyncio

from structlog import get_logger

from models.business_model import BusinessMetadata
from services.business_service import BusinessService

logger = get_logger(__name__)


class BusinessContextService:
    def __init__(self):
        self.business_service = BusinessService()

    async def extract_contexts_by_product(self, product_mapping: dict) -> dict:
        """Extract business metadata + features per unique product_id,
        merge into each product_mapping entry, and return enriched mapping.

        Adds brand_info, unique_features to each product entry.

        TODO: Cache extracted contexts in storage per product_id.
        Fetch from cache instead of re-calling LLM on every optimization run.
        Only re-extract when a rescrape updates the summary.
        """
        unique_products: dict[str, dict] = {}
        for product_details in product_mapping.values():
            pid = product_details["product_id"]
            if pid not in unique_products:
                unique_products[pid] = {
                    "summary": product_details.get("summary", ""),
                    "business_url": product_details.get("business_url", ""),
                }

        results = await asyncio.gather(
            *[
                self._extract_product_context(pid, product_info)
                for pid, product_info in unique_products.items()
            ]
        )
        contexts_by_product = dict(results)

        for product_details in product_mapping.values():
            pid = product_details["product_id"]
            context = contexts_by_product.get(pid, _empty_context())
            product_details["brand_info"] = context["brand_info"]
            product_details["unique_features"] = context["unique_features"]

        return product_mapping

    async def _extract_product_context(
        self, pid: str, product_info: dict
    ) -> tuple[str, dict]:
        summary = product_info["summary"]
        url = product_info["business_url"]
        if not summary:
            return pid, _empty_context()

        results = await asyncio.gather(
            self.business_service.extract_business_metadata(summary, url),
            self.business_service.extract_business_unique_features(summary),
            return_exceptions=True,
        )
        metadata = (
            results[0] if not isinstance(results[0], Exception) else BusinessMetadata()
        )
        features = results[1] if not isinstance(results[1], Exception) else []
        return pid, {
            "brand_info": metadata,
            "unique_features": features,
        }


def _empty_context() -> dict:
    return {"brand_info": BusinessMetadata(), "unique_features": []}


business_context_service = BusinessContextService()
