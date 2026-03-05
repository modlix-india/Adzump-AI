from typing import Any

from adapters.meta.client import meta_client


class MetaAccountsAdapter:
    async def list_business_accounts(self, client_code: str) -> list[dict[str, Any]]:
        result = await meta_client.get(
            "/me/businesses",
            client_code=client_code,
            params={"fields": "id,name"},
        )
        return [
            {"id": b["id"], "name": b.get("name", b["id"])}
            for b in result.get("data", [])
        ]

    async def list_ad_accounts(
        self, business_id: str, client_code: str
    ) -> list[dict[str, Any]]:
        result = await meta_client.get(
            f"/{business_id}/owned_ad_accounts",
            client_code=client_code,
            params={"fields": "id,name,account_status"},
        )
        return [
            {"id": a["id"], "name": a.get("name", a["id"])}
            for a in result.get("data", [])
            if a.get("account_status") == 1
        ]
