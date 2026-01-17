from fastapi import HTTPException
import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict
from structlog import get_logger

from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService

logger = get_logger(__name__)


class WhatsAppAssetsService(BaseAssetService):
    MAX_STARTER_MESSAGE_LENGTH = 140
    MAX_CTA_DESCRIPTION_LENGTH = 30
    MAX_LLM_RETRIES = 3

    # =========================
    # Public API (called outside)
    # =========================
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
            data_object_id=data_object_id,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )

        summary = product_data.get("summary", "")
        links = product_data.get("siteLinks", [])

        if not summary:
            raise HTTPException(
                status_code=400,
                detail="Missing or empty 'summary' in product data",
            )

        # -------- Extract WhatsApp number --------
        phone_number = WhatsAppAssetsService.extract_whatsapp_number_from_links(links)

        # -------- Generate validated asset --------
        asset = await WhatsAppAssetsService._generate_valid_asset(summary)

        result = [
            {
                "starter_message": asset.get("starter_message", ""),
                "call_to_action_selection": asset.get("call_to_action_selection", ""),
                "call_to_action_description": asset.get(
                    "call_to_action_description", ""
                ),
                "phone_number": phone_number,
            }
        ]

        logger.info("Final WhatsApp asset prepared", result=result)
        return result

    # =========================
    # Helper functions
    # =========================
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
                phone = parse_qs(parsed.query).get("phone")
                if phone:
                    return re.sub(r"\D", "", phone[0])

            # whatsapp://send?phone=<number>
            if href.startswith("whatsapp://"):
                parsed = urlparse(href)
                phone = parse_qs(parsed.query).get("phone")
                if phone:
                    return re.sub(r"\D", "", phone[0])

        return ""

    # =========================
    # Internal / private helpers
    # =========================
    @staticmethod
    def _is_valid_llm_response(llm_result: object) -> bool:
        return (
            isinstance(llm_result, list)
            and len(llm_result) > 0
            and isinstance(llm_result[0], dict)
        )

    @staticmethod
    async def _generate_llm_asset(summary: str) -> Dict:
        llm_result = await BaseAssetService.generate_from_prompt(
            "whatsapp_asset_prompt.txt",
            {"summary": summary},
        )

        logger.info("LLM response received", llm_result=llm_result)

        if not WhatsAppAssetsService._is_valid_llm_response(llm_result):
            logger.error("Invalid LLM response format", llm_result=llm_result)
            raise HTTPException(
                status_code=500,
                detail="LLM did not return a valid WhatsApp asset array",
            )

        return llm_result[0]

    @staticmethod
    def _is_valid_asset(asset: Dict) -> bool:
        starter_message = asset.get("starter_message", "")
        cta_description = asset.get("call_to_action_description", "")

        return (
            len(starter_message) <= WhatsAppAssetsService.MAX_STARTER_MESSAGE_LENGTH
            and len(cta_description) <= WhatsAppAssetsService.MAX_CTA_DESCRIPTION_LENGTH
        )

    @staticmethod
    async def _generate_valid_asset(summary: str) -> Dict:
        for attempt in range(WhatsAppAssetsService.MAX_LLM_RETRIES):
            asset = await WhatsAppAssetsService._generate_llm_asset(summary)

            if WhatsAppAssetsService._is_valid_asset(asset):
                logger.info(
                    "Valid WhatsApp asset generated",
                    attempt=attempt + 1,
                )
                return asset

            logger.info(
                "WhatsApp asset validation failed, retrying",
                attempt=attempt + 1,
                starter_length=len(asset.get("starter_message", "")),
                cta_length=len(asset.get("call_to_action_description", "")),
            )

        raise HTTPException(
            status_code=500,
            detail="Unable to generate valid WhatsApp asset within limits",
        )
