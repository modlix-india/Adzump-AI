from typing import Any

from adapters.meta.client import meta_client


class MetaCampaignAdapter:
    async def create(
        self,
        client_code: str,
        ad_account_id: str,
        payload: dict[str, Any],
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        account_id = ad_account_id.removeprefix("act_")
        return await meta_client.post(
            f"/act_{account_id}/campaigns",
            client_code=client_code,
            json={**payload, "status": status},
        )

    async def get(
        self,
        client_code: str,
        campaign_id: str,
    ) -> dict[str, Any]:
        return await meta_client.get(
            f"/{campaign_id}",
            client_code=client_code,
        )

    async def list(
        self,
        client_code: str,
        ad_account_id: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        account_id = ad_account_id.removeprefix("act_")
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return await meta_client.get(
            f"/act_{account_id}/campaigns",
            client_code=client_code,
            params=params or None,
        )
