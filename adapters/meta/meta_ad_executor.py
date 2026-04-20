from core.infrastructure.context import auth_context
from adapters.meta.exceptions import MetaAPIContractError
from adapters.meta.client import MetaClient
from core.models.meta import AdCreationStage


class MetaAdExecutor:
    STAGE_MAP = {
        AdCreationStage.CAMPAIGN: "campaigns",
        AdCreationStage.ADSET: "adsets",
        AdCreationStage.CREATIVE: "adcreatives",
        AdCreationStage.AD: "ads",
    }

    def __init__(self, meta_client: MetaClient, ad_account_id: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id

    async def _post_and_extract_id(self, endpoint: str, payload: dict) -> str:
        client_code = auth_context.client_code
        response = await self.meta_client.post(
            endpoint=endpoint, json=payload, client_code=client_code
        )

        entity_id = response.get("id")
        if not entity_id:
            raise MetaAPIContractError(
                f"Meta API responded successfully but missing 'id': {response}"
            )

        return entity_id

    async def create_entity(self, stage: AdCreationStage, payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/{self.STAGE_MAP[stage]}"
        return await self._post_and_extract_id(endpoint, payload)
