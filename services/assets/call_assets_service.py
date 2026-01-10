from fastapi import HTTPException
from typing import List
import re
import json
from services.business_service import BusinessService


class CallAssetsService:
    @staticmethod
    def extract_phone_numbers(text: str) -> List[str]:
        if not text:
            return []

        pattern = re.compile(
            r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,5}\)?[-.\s]?)?\d{3,5}[-.\s]?\d{4,6}"
        )
        matches = re.findall(pattern, text)
        return [m.strip() for m in matches if m]

    @staticmethod
    def clean_phone_numbers(numbers: List[str]) -> List[str]:
        valid_numbers = set()
        allowed_starts = {"6", "7", "8", "9"}

        for num in numbers:
            digits = re.sub(r"\D", "", num)

            if len(digits) == 10 and digits[0] in allowed_starts:
                valid_numbers.add("+91" + digits)

            elif (
                len(digits) == 12
                and digits.startswith("91")
                and digits[2] in allowed_starts
            ):
                valid_numbers.add("+" + digits)

            else:
                continue

        return list(valid_numbers)[:3]

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

        # Extract numbers from tel: links
        tel_numbers = [
            link.get("href", "").replace("tel:", "").strip()
            for link in links
            if link.get("href", "").startswith("tel:")
        ]

        # Extract numbers from links JSON
        link_text_data = json.dumps(links)
        link_numbers = CallAssetsService.extract_phone_numbers(link_text_data)

        # Extract numbers from summary as fallback
        summary_numbers = CallAssetsService.extract_phone_numbers(summary)

        # Combine all sources
        all_numbers = tel_numbers + link_numbers + summary_numbers

        # Clean + validate + deduplicate + limit
        cleaned_numbers = CallAssetsService.clean_phone_numbers(all_numbers)

        if not cleaned_numbers:
            return []

        structured_numbers = [
            {"phoneNumber": num, "countryCode": "IN"} for num in cleaned_numbers
        ]

        return structured_numbers
