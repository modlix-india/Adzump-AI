from typing import Any, List
import os
import structlog

from adapters.meta.client import MetaClient


class MetaAdSetAdapter:
    def _get_client(self) -> MetaClient:
        meta_token = os.getenv("META_ACCESS_TOKEN", "")
        return MetaClient(meta_token)

    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        return ad_account_id.removeprefix("act_")


    async def fetch_available_languages(
        self,
        ad_account_id: str = None,
        queries: List[str] = None,
    ) -> List[dict]:
        """
        Fetch all available languages from Meta using the /search endpoint.
        
        The /search endpoint with type='adlocale' returns all supported locales
        with their short 'key' IDs (e.g., 1001 for English (All), 46 for Hindi).
        
        Note: ad_account_id and queries parameters are kept for backwards compatibility
        but are not used since /search returns all locales globally.
        """
        
        logger = structlog.get_logger()
        client = self._get_client()

        try:
            response = await client.get(
                "/search",
                params={"type": "adlocale", "q": ""},
            )
            data = response.get("data", [])
            
            available_locales = [
                {
                    "id": item.get("key"),
                    "name": item.get("name"),
                }
                for item in data
                if item.get("key") and item.get("name")
            ]
            
            logger.info("Fetched all locales from /search", count=len(available_locales))
            return available_locales
            
        except Exception as e:
            logger.error("Failed to fetch locales from /search", error=str(e))

            return []



    async def create(
        self,
        ad_account_id: str,
        campaign_id: str,
        meta_payload,
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        client = self._get_client()
        account_id = self._normalize_ad_account_id(ad_account_id)

        return await client.post(
            f"/act_{account_id}/adsets",
            json=meta_payload,
        )
