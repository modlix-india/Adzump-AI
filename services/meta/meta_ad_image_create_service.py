import httpx
from fastapi import HTTPException
from config.meta import META_BASE_URL, META_HTTP_TIMEOUT


class MetaAdImageCreateService:

    @staticmethod
    async def upload_image(
        ad_account_id: str,
        access_token: str,
        image_base64: str
    ):
        url = f"{META_BASE_URL}/act_{ad_account_id}/adimages"

        payload = {
            "bytes": image_base64
        }

        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {access_token}"
                }
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=response.json()
            )

        return response.json()
