from fastapi import HTTPException
from urllib.parse import urlparse
from typing import List, Dict, Any
import json
from utils.text_utils import is_internal_link
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessInfoService


class SitelinksService(BaseAssetService,BusinessInfoService):
    
    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str):
        product_data = await BusinessInfoService.fetch_product_details(data_object_id, access_token, client_code)

        summary = product_data.get("summary", "")
        base_url = product_data.get("businessUrl", "")
        links = product_data.get("siteLinks", [])

        if not base_url or not summary:
            raise HTTPException(status_code=400, detail="Missing 'summary' or 'businessUrl'")

        base_domain = urlparse(base_url).netloc.replace("www.", "").lower()

        valid_links = [
            l for l in links
            if l.get("text", "").strip()
            and l.get("href", "").strip()
            and is_internal_link(l["href"], base_domain)
        ]

        if not valid_links:
            return []

        sitelinks = await BaseAssetService.generate_from_prompt(
            "sitelinks_prompt.txt",
            {"summary": summary, "base_url": base_url, "links_json": json.dumps(valid_links, indent=2)}
        )

        formatted = []
        for s in sitelinks:
            formatted.append({
                "sitelink_text": s.get("sitelink_text", "")[:25],
                "description_1": s.get("description_1", "")[:35],
                "description_2": s.get("description_2", "")[:35],
                "final_url": s.get("final_url", "")
            })

        return formatted
