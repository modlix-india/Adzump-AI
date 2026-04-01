from core.infrastructure.context import auth_context
from adapters.meta.exceptions import MetaAPIContractError


class MetaAdExecutor:
    def __init__(self, meta_client, ad_account_id: str):
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

    async def create_campaign(self, payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/campaigns"
        return await self._post_and_extract_id(endpoint, payload)

    async def create_adset(self, payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/adsets"
        return await self._post_and_extract_id(endpoint, payload)

    async def create_creative(self, payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/adcreatives"
        return await self._post_and_extract_id(endpoint, payload)

    async def create_ad(self, payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/ads"
        return await self._post_and_extract_id(endpoint, payload)
