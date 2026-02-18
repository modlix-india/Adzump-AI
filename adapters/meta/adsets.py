from typing import Any

from adapters.meta.client import meta_client


class MetaAdSetAdapter:
    async def search_ad_locale(
        self,
        client_code: str,
        language_name: str,
    ) -> dict | None:
        response = await meta_client.get(
            "/search",
            client_code=client_code,
            params={"type": "adlocale", "q": language_name},
        )
        requested = language_name.strip().lower()
        for item in response.get("data", []):
            if item.get("name", "").lower().startswith(requested):
                return {"id": item.get("key"), "name": item.get("name")}
        return None

    async def create(
        self,
        client_code: str,
        ad_account_id: str,
        campaign_id: str,
        meta_payload: dict,
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        account_id = ad_account_id.removeprefix("act_")
        return await meta_client.post(
            f"/act_{account_id}/adsets",
            client_code=client_code,
            json={
                **meta_payload,
                "campaign_id": campaign_id,
                "status": status,
            },
        )
