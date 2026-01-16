from fastapi import HTTPException
import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict
import logging

from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService

logger = logging.getLogger(__name__)


class WhatsAppAssetsService(BaseAssetService):
    @staticmethod
    def extract_whatsapp_number_from_links(links: List[Dict]) -> str:
        for link in links:
            href = (link.get("href") or "").strip()
            if not href:
                continue

            # wa.me/<number>
            wa_match = re.search(r"wa\.me/(\d{10,15})", href)
            if wa_match:
                return wa_match.group(1)

            # api.whatsapp.com/send?phone=<number>
            if "api.whatsapp.com/send" in href:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                phone = qs.get("phone")
                if phone:
                    return re.sub(r"\D", "", phone[0])

            # whatsapp://send?phone=<number>
            if href.startswith("whatsapp://"):
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                phone = qs.get("phone")
                if phone:
                    return re.sub(r"\D", "", phone[0])

        return ""

    @staticmethod
    async def generate(
        data_object_id: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str = "",
        x_forwarded_port: str = "",
    ) -> List[Dict]:
        # -------- Fetch product details --------
        product_data = await BusinessService.fetch_product_details(
            data_object_id,
            access_token,
            client_code,
            x_forwarded_host,
            x_forwarded_port,
        )

        summary = product_data.get("summary", "")
        links = product_data.get("siteLinks", [])

        logger.info("Product summary:", summary)
        logger.info("Product links:", links)

        if not summary:
            raise HTTPException(
                status_code=400, detail="Missing or empty 'summary' in product data"
            )

        # -------- Extract WhatsApp number (STRICT) -------
        phone_number = WhatsAppAssetsService.extract_whatsapp_number_from_links(links)

        if not phone_number:
            logger.info("No WhatsApp number found in WhatsApp links; setting empty")
            phone_number = ""

        logger.info("WhatsApp number:", phone_number)

        # -------- Call LLM --------
        llm_result = await BaseAssetService.generate_from_prompt(
            "whatsapp_asset_prompt.txt", {"summary": summary}
        )
        logger.info("Raw LLM result:", llm_result)
        if (
            not isinstance(llm_result, list)
            or len(llm_result) == 0
            or not isinstance(llm_result[0], dict)
        ):
            raise HTTPException(
                status_code=500,
                detail="LLM did not return a valid WhatsApp asset array",
            )

        asset = llm_result[0]
        result = [
            {
                "starter_message": asset.get("starter_message"),
                "call_to_action_selection": asset.get("call_to_action_selection"),
                "call_to_action_description": asset.get("call_to_action_description"),
                "phone_number": phone_number,
            }
        ]

        logger.info("Final WhatsApp asset prepared:", result)
        return result
