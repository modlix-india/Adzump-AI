from typing import Any
from datetime import datetime

from adapters.meta.client import MetaClient
from core.infrastructure.context import auth_context


class MetaCreativeAdapter:
    def _get_client(self) -> MetaClient:
        return MetaClient(meta_token)

    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        return ad_account_id.removeprefix("act_")

    async def create(
        self,
        ad_account_id: str,
        creative_payload: dict[str, Any],
        page_id: str,
    ) -> dict[str, Any]:
        client = self._get_client()
        account_id = self._normalize_ad_account_id(ad_account_id)

        text = creative_payload["text"]

        image = creative_payload.get("image")
        if not image or not image.get("image_hash"):
            raise ValueError("image_hash is required to create Meta creative")

        object_story_spec = {
            "page_id": page_id,
        }

        asset_feed_spec = {
            "images": [
                {"hash": image["image_hash"]}
            ],
            "bodies": [
                {"text": pt} for pt in text["primary_texts"]
            ],
            "titles": [
                {"text": h} for h in text["headlines"]
            ],
            "descriptions": [
                {"text": d} for d in text["descriptions"]
            ],
            "call_to_action_types": [text["cta"]],
        }



        payload = {
            "name": f"Creative {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "object_story_spec": object_story_spec,
            "asset_feed_spec": asset_feed_spec,
        }

        return await client.post(
            f"/act_{account_id}/adcreatives",
            auth_context.client_code,
            json=payload,
        )
