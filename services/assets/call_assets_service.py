from fastapi import HTTPException
from typing import List
import re
import json
from services.business_service import BusinessService



class CallAssetsService():
    
    @staticmethod
    def extract_phone_numbers(text: str) -> List[str]:
        pattern = re.compile(
            r'(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,5}\)?[-.\s]?)?\d{3,5}[-.\s]?\d{4,6}'
        )
        matches = re.findall(pattern, text or "")
        return [m.strip() for m in matches if len(m.strip()) >= 7]

    @staticmethod
    def clean_phone_numbers(numbers: List[str]) -> List[str]:
        cleaned_phone_numbers = []
        for num in numbers:
            digits = re.sub(r'\D', '', num)
            if 10 <= len(digits) <= 13:
                # Convert to +91 if 10-digit (India assumption)
                if len(digits) == 10:
                    digits = "+91" + digits
                elif not digits.startswith("+"):
                    digits = "+" + digits
                cleaned_phone_numbers.append(digits)
        # Deduplicate
        return list(set(cleaned_phone_numbers))

    @staticmethod
    async def generate(data_object_id: str, access_token: str, client_code: str,x_forwarded_host=str,
            x_forwarded_port=str) -> List[str]:
        product_data = await BusinessService.fetch_product_details(
            data_object_id, access_token, client_code,x_forwarded_host,x_forwarded_port
        )

        if not product_data:
            raise HTTPException(status_code=500, detail="Invalid product data response")

        summary = product_data.get("summary", "")
        links = product_data.get("siteLinks", [])

        # --- Extract numbers from tel: links ---
        tel_numbers = [
            link.get("href", "").replace("tel:", "").strip()
            for link in links
            if link.get("href", "").startswith("tel:")
        ]

        # --- Extract numbers from JSON of links ---
        link_text_data = json.dumps(links)
        text_numbers = CallAssetsService.extract_phone_numbers(link_text_data)

        # --- Extract numbers from summary as fallback ---
        summary_numbers = CallAssetsService.extract_phone_numbers(summary)

        # Combine all sources
        all_numbers = tel_numbers + text_numbers + summary_numbers

        # Clean & deduplicate
        cleaned_phone_numbers = CallAssetsService.clean_phone_numbers(all_numbers)

        if not cleaned_phone_numbers:
            return []

        structured_numbers = [
            {"phoneNumber": num, "countryCode": "IN"} for num in cleaned_phone_numbers
        ]

        return structured_numbers
