class MetaCreativeExecutor:
    def __init__(self, meta_client, ad_account_id: str, client_code: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id
        self.client_code = client_code

    async def create_creative(self, creative_payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/adcreatives"

        response = await self.meta_client.post(
            endpoint=endpoint,
            json=creative_payload,
            client_code=self.client_code
        )

        creative_id = response.get("id")
        if not creative_id:
            raise ValueError(f"Meta API responded successfully but missing 'id': {response}")

        return creative_id
