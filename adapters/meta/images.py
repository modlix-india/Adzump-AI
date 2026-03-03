from adapters.meta.client import meta_client
from core.infrastructure.context import auth_context

class MetaAdImageAdapter:

    async def upload_image(
        self,
        ad_account_id: str,
        image_base64: str,
    ) -> dict:
        account_id = ad_account_id.removeprefix("act_")

        payload = {
            "bytes": image_base64
        }

        return await meta_client.post(
            f"/act_{account_id}/adimages",
            auth_context.client_code,
            json=payload,
        )
