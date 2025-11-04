from fastapi import HTTPException
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessInfoService


class CalloutsService(BaseAssetService,BusinessInfoService):
    
    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str):
        product_data = await BusinessInfoService.fetch_product_details(data_object_id, access_token, client_code)
        summary = product_data.get("summary", "")

        if not summary:
            raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

        callouts = await BaseAssetService.generate_from_prompt(
            "callouts_prompt.txt", {"summary": summary}
        )

        return [{"callout_text": c[:25]} for c in callouts if isinstance(c, str) and c.strip()]
