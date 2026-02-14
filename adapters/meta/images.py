import os
from adapters.meta.client import MetaClient

class MetaAdImageAdapter:
    def _get_client(self) -> MetaClient:
        meta_token = os.getenv("META_ACCESS_TOKEN", "")
        if not meta_token:
            raise ValueError("META_ACCESS_TOKEN not configured")
        return MetaClient(meta_token)

    async def upload_image(
        self,
        ad_account_id: str,
        image_base64: str,
    ) -> dict:
        client = self._get_client()
        account_id = ad_account_id.removeprefix("act_")

        payload = {
            "bytes": image_base64
        }

        return await client.post(
            f"/act_{account_id}/adimages",
            json=payload,
        )
