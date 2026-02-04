from typing import Any
import os

from adapters.meta.client import MetaClient


class MetaAdSetAdapter:
    def _get_client(self) -> MetaClient:
        meta_token = os.getenv("META_ACCESS_TOKEN", "")
        return MetaClient(meta_token)

    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        return ad_account_id.removeprefix("act_")

    async def create(
        self,
        ad_account_id: str,
        campaign_id: str,
        payload,
        status: str = "PAUSED",
    ) -> dict[str, Any]:
        client = self._get_client()
        account_id = self._normalize_ad_account_id(ad_account_id)

        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()

        targeting = payload.get("targeting", {})

        if "genders" in targeting and not targeting["genders"]:
            targeting.pop("genders")

        daily_budget = payload.get("daily_budget") or targeting.get("daily_budget")
        if not daily_budget:
            raise ValueError("daily_budget is required")
        
        if "daily_budget" in targeting:
            targeting.pop("daily_budget")

        daily_budget = max(100, int(daily_budget))    

        meta_payload = {
            "name": payload["adset_name"],
            "campaign_id": campaign_id,
            "daily_budget": daily_budget * 100,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LEAD_GENERATION",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "status": status,
            "targeting": targeting,
        }

        return await client.post(
            f"/act_{account_id}/adsets",
            json=meta_payload,
        )
