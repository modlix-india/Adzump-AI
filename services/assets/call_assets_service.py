from fastapi import HTTPException
import json
from typing import List
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService
import re


class CallAssetsService(BaseAssetService):
    @staticmethod
    def extract_possible_numbers(text: str) -> List[str]:
        if not text:
            return []
        pattern = re.compile(r"\+?\d[\d\-\s().]{6,20}")
        return [m.strip() for m in re.findall(pattern, text)]

    @staticmethod
    def normalize_number(num: str) -> str:
        if not num:
            return ""
        num = num.strip()
        if num.startswith("+"):
            return "+" + re.sub(r"\D", "", num[1:])
        return re.sub(r"\D", "", num)

    @staticmethod
    async def generate(
        data_object_id: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
    ) -> List[dict]:
        product_data = await BusinessService.fetch_product_details(
            data_object_id,
            access_token,
            client_code,
            x_forwarded_host,
            x_forwarded_port,
        )

        if not product_data:
            raise HTTPException(status_code=500, detail="Invalid product data response")

        summary = product_data.get("summary", "")
        links = product_data.get("siteLinks", [])

        # 1. tel: links
        tel_numbers = [
            link.get("href", "").replace("tel:", "").strip()
            for link in links
            if link.get("href", "").startswith("tel:")
        ]

        # 2. extract numbers
        link_numbers = CallAssetsService.extract_possible_numbers(json.dumps(links))
        summary_numbers = CallAssetsService.extract_possible_numbers(summary)

        # 3. Normalize + Deduplicate
        raw_numbers = list(
            {
                CallAssetsService.normalize_number(n)
                for n in (tel_numbers + link_numbers + summary_numbers)
                if n
            }
        )

        if not raw_numbers:
            return []

        # 4. LLM validation (country-aware)
        call_assets = await BaseAssetService.generate_from_prompt(
            "callAsset_prompt.txt", {"raw_numbers": raw_numbers}
        )

        if not call_assets:
            return []

        return call_assets[:3]
