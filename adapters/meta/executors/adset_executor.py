class MetaAdSetExecutor:
    def __init__(self, meta_client, ad_account_id: str, client_code: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id
        self.client_code = client_code

    async def create_adset(self, adset_payload: dict, campaign_id: str) -> str:
        endpoint = f"/act_{self.ad_account_id}/adsets"

        payload = {
            **adset_payload,
            "campaign_id": campaign_id
        }

        response = await self.meta_client.post(
            endpoint=endpoint,
            json=payload,
            client_code=self.client_code
        )

        adset_id = response.get("id")
        if not adset_id:
            raise ValueError(f"Meta API responded successfully but missing 'id': {response}")

        return adset_id
