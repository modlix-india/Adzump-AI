import httpx
from fastapi import HTTPException

META_BASE_URL = "https://graph.facebook.com/v21.0"


class MetaCampaignCreateService:

    @staticmethod
    async def create_campaign(
        ad_account_id: str,
        access_token: str,
        campaign_payload: dict
    ):
        url = f"{META_BASE_URL}/act_{ad_account_id}/campaigns"

        payload = {
            **campaign_payload,
            "status": "PAUSED"
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=response.json()
            )

        return response.json()

