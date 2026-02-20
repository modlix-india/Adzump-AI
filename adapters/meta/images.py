from adapters.meta.client import MetaClient
from core.infrastructure.context import auth_context

class MetaAdImageAdapter:
    def _get_client(self) -> MetaClient:
        return MetaClient()

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
            auth_context.client_code,
            json=payload,
        )
