from fastapi import HTTPException
from urllib.parse import urlparse
import json
from utils.text_utils import is_internal_link, is_valid_length
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService

MAX_SITELINK_TEXT = 25
MAX_DESCRIPTION = 35

class SitelinksService(BaseAssetService):
    
    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str,x_forwarded_host=str,
            x_forwarded_port=str):
        product_data = await BusinessService.fetch_product_details(data_object_id, access_token, client_code,x_forwarded_host,
            x_forwarded_port)

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

        def enforce_absolute_url(href: str, base_url: str) -> str | None:
            if not href:
                return None

            href = href.strip()

            if href.startswith(("javascript", "tel:", "#")):
                return None

            if href.startswith(("http://", "https://")):
                return href

            if href.startswith("/"):
                return f"{base_url.rstrip('/')}/{href.lstrip('/')}"

            return None


        formatted = []
        seen_urls = set()

        for s in sitelinks:
            final_url = enforce_absolute_url(
                s.get("final_url", ""),
                base_url
            )

            if not final_url:
                continue

            sitelink_text = s.get("sitelink_text", "").strip()
            description_1 = s.get("description_1", "").strip()
            description_2 = s.get("description_2", "").strip()

            if not is_valid_length(sitelink_text, MAX_SITELINK_TEXT):
                continue
            if not is_valid_length(description_1, MAX_DESCRIPTION):
                continue
            if not is_valid_length(description_2, MAX_DESCRIPTION):
                continue

            if final_url in seen_urls:
                continue

            seen_urls.add(final_url)

            formatted.append({
                "sitelink_text": sitelink_text,
                "description_1": description_1,
                "description_2": description_2,
                "final_url": final_url,
            })
            if len(formatted) == 6:
                break

        return formatted

