class MetaCampaignExecutor:
    def __init__(self, meta_client, ad_account_id: str, client_code: str):
        self.meta_client = meta_client
        self.ad_account_id = ad_account_id
        self.client_code = client_code

    async def create_campaign(self, campaign_payload: dict) -> str:
        endpoint = f"/act_{self.ad_account_id}/campaigns"

        response = await self.meta_client.post(
            endpoint=endpoint,
            json=campaign_payload,
            client_code=self.client_code
        )

        campaign_id = response.get("id")
        if not campaign_id:
            raise ValueError(f"Meta API responded successfully but missing 'id': {response}")

        return campaign_id
