import httpx
from fastapi import HTTPException
from config.meta import META_BASE_URL, META_HTTP_TIMEOUT


class MetaAdSetCreateService:

    @staticmethod
    async def create_adset(
        ad_account_id: str,
        access_token: str,
        campaign_id: str,
        adset_payload: dict,
    ):
        url = f"{META_BASE_URL}/act_{ad_account_id}/adsets"

        targeting = adset_payload.get("targeting", {})
        if "genders" in targeting and not targeting["genders"]:
            targeting.pop("genders")

        payload = {
            "name": adset_payload["adset_name"],
            "campaign_id": campaign_id,
            "daily_budget": 50000,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LEAD_GENERATION",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "status": "PAUSED",
            "targeting": targeting
        }

        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json()
            )

        return response.json()
