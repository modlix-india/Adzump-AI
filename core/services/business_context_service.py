from typing import Any


import asyncio

from structlog import get_logger

from models.business_model import BusinessMetadata
from services.business_service import BusinessService

logger = get_logger(__name__)


class BusinessContextService:
    def __init__(self):
        self.business_service = BusinessService()

    async def extract_contexts_by_product(
        self, campaign_mapping: dict
    ) -> dict[str, dict]:
        """Extract business metadata + features per unique product_id.
        Returns: {product_id: {brand_info, unique_features, summary, url}}

        TODO: Cache extracted contexts in storage per product_id.
        Fetch from cache instead of re-calling LLM on every optimization run.
        Only re-extract when a rescrape updates the summary.
        """
        product_contexts: dict[str, dict] = {}
        for campaign_details in campaign_mapping.values():
            pid = campaign_details["product_id"]
            if pid not in product_contexts:
                product_contexts[pid] = {
                    "summary": campaign_details.get("summary", ""),
                    "business_url": campaign_details.get("business_url", ""),
                }

        results = await asyncio.gather(
            *[
                self._extract_product_context(pid, product_info)
                for pid, product_info in product_contexts.items()
            ]
        )
        return dict[str, dict](results)

    async def _extract_product_context(
        self, pid: str, product_info: dict
    ) -> tuple[str, dict]:
        summary = product_info["summary"]
        url = product_info["business_url"]
        if not summary:
            return pid, empty_context()

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
            "summary": summary,
            "url": url,
        }


def empty_context() -> dict:
    return {
        "brand_info": BusinessMetadata(),
        "unique_features": [],
        "summary": "",
        "url": "",
    }


business_context_service = BusinessContextService()
