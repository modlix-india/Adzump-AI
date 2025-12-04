from fastapi import HTTPException
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService


class CalloutsService(BaseAssetService):
    
    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str,x_forwarded_host=str,
            x_forwarded_port=str):
        product_data = await BusinessService.fetch_product_details(data_object_id, access_token, client_code,x_forwarded_host,
            x_forwarded_port)
        summary = product_data.get("summary", "")

        if not summary:
            raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

        callouts = await BaseAssetService.generate_from_prompt(
            "callouts_prompt.txt", {"summary": summary}
        )

        valid_callouts = [
            {"callout_text": c}
            for c in callouts
            if isinstance(c, str) and len(c) <= 25
        ]

        return valid_callouts
