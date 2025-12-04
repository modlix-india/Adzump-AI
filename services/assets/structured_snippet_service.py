from fastapi import HTTPException
import json

from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService


class StructuredSnippetsService(BaseAssetService):

    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str,x_forwarded_host: str,
        x_forwarded_port: str):
        product_data = await BusinessService.fetch_product_details(
            data_object_id, access_token, client_code,x_forwarded_host,x_forwarded_port
        )

        summary = product_data.get("summary", "")
        if not summary:
            raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

        snippets = await BaseAssetService.generate_from_prompt(
            "structured_snippet_prompt.txt",
            {"summary": summary}
        )
        formatted = []
        for s in snippets:
            header = s.get("header", "")[:25]
            values = [v[:25] for v in s.get("values", []) if v.strip()]
            if header and values:
                formatted.append({"header": header, "values": values})
        return formatted
