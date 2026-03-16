class MetaAdExecutor:
    def __init__(self, meta_client, ad_account_id: str, client_code: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id
        self.client_code = client_code

    async def create_ad(
        self,
        ad_payload: dict,
        adset_id: str,
        creative_id: str
    ) -> str:
        endpoint = f"/act_{self.ad_account_id}/ads"

        payload = {
            **ad_payload,
            "adset_id": adset_id,
            "creative": {
                "creative_id": creative_id
            }
        }

        response = await self.meta_client.post(
            endpoint=endpoint,
            json=payload,
            client_code=self.client_code
        )

        ad_id = response.get("id")
        if not ad_id:
            raise ValueError(f"Meta API responded successfully but missing 'id': {response}")

        return ad_id
