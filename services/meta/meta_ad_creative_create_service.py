import httpx
from fastapi import HTTPException
from config.meta import META_BASE_URL, META_HTTP_TIMEOUT


class MetaAdCreativeCreateService:

    @staticmethod
    async def create_creative(
        ad_account_id: str,
        access_token: str,
        image_hash: str,
        headline: str,
        primary_text: str,
        cta: str
    ):
        url = f"{META_BASE_URL}/act_{ad_account_id}/adcreatives"

        payload = {
            "object_story_spec": {
                "link_data": {
                    "image_hash": image_hash,
                    "message": primary_text,
                    "name": headline,
                    "call_to_action": {
                        "type": cta.replace(" ", "_").upper()
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"}
            )

        if response.status_code != 200:
            raise HTTPException(500, response.json())

        return response.json()
