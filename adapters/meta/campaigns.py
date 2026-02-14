from typing import Any

from adapters.meta.client import MetaClient
from core.infrastructure.context import auth_context
from oserver.services.connection import fetch_meta_api_token


class MetaCampaignAdapter:
    """Adapter for Meta Campaign CRUD operations."""

    def _get_client(self) -> MetaClient:
        meta_token = fetch_meta_api_token(auth_context.client_code)
        # meta_token = os.getenv("META_ACCESS_TOKEN", "")
        return MetaClient(meta_token)

    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        """Strip act_ prefix if present to avoid duplication."""
        return ad_account_id.removeprefix("act_")

    async def create(
        self,
        ad_account_id: str,
        payload: dict[str, Any],
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        """Create a campaign in Meta Ads."""
        client = self._get_client()
        account_id = self._normalize_ad_account_id(ad_account_id)
        return await client.post(
            f"/act_{account_id}/campaigns",
            json={**payload, "status": status},
        )

    async def get(self, campaign_id: str) -> dict[str, Any]:
        """Get campaign details."""
        client = self._get_client()
        return await client.get(f"/{campaign_id}")

    async def list(
        self,
        ad_account_id: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """List campaigns for an ad account."""
        client = self._get_client()
        account_id = self._normalize_ad_account_id(ad_account_id)
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return await client.get(
            f"/act_{account_id}/campaigns",
            params=params or None,
        )
