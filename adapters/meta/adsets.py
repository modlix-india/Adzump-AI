from typing import Any, List
import os
import structlog

from adapters.meta.client import MetaClient

logger = structlog.get_logger()


class MetaAdSetAdapter:
    def _get_client(self) -> MetaClient:
        meta_token = os.getenv("META_ACCESS_TOKEN", "")
        return MetaClient(meta_token)

    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        return ad_account_id.removeprefix("act_")

    async def resolve_locale_by_name(self, language_name: str) -> dict | None:
        client = self._get_client()

        try:
            response = await client.get(
                "/search",
                params={"type": "adlocale", "q": language_name},
            )

            data = response.get("data", [])
            requested = language_name.strip().lower()

            for item in data:
                meta_name = item.get("name", "").lower()

                if requested in meta_name:
                    return {
                        "id": item.get("key"),
                        "name": item.get("name"),
                    }

            logger.warning(
                "Locale not found in Meta",
                language=language_name,
            )
            return None

        except Exception as e:
            logger.error(
                "Failed to resolve locale",
                language=language_name,
                error=str(e),
            )
            return None


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
