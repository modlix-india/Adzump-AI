import logging
import json
from typing import List, Tuple
from pydantic import ValidationError

from utils import prompt_loader
from services.openai_client import chat_completion
from oserver import connection
from models.keyword_model import BusinessMetadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BusinessInfoService:

    OPENAI_MODEL = "gpt-4o-mini"

    async def extract_business_metadata(
        self, scraped_data: str, url: str = None
    ) -> BusinessMetadata:
        try:
            prompt = prompt_loader.format_prompt(
                'business_metadata_prompt.txt',
                scraped_data=scraped_data,
                url=url
            )

            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=500,
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            raw = resp.choices[0].message.content.strip()
            data = json.loads(raw)

            brand_info = BusinessMetadata(**data)
            logger.info(f"Extracted brand info: {brand_info.model_dump()}")
            return brand_info

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed: {e}, using defaults")
            return BusinessMetadata()
        except ValidationError as e:
            logger.warning(f"Model validation failed: {e}, using partial data")
            valid_data = {}
            for field in BusinessMetadata.model_fields:
                if field in data and isinstance(data[field], (str, list, int, float)):
                    valid_data[field] = data[field]
            return BusinessMetadata(**valid_data)
        except Exception as e:
            logger.warning(f"Brand extraction failed: {e}, using defaults")
            return BusinessMetadata()

    async def extract_business_unique_features(self, scraped_data: str) -> List[str]:

        prompt = prompt_loader.format_prompt(
            'business_usp_prompt.txt',
            scraped_data=scraped_data
        )

        try:
            resp = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.OPENAI_MODEL,
                max_tokens=400,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            usp_data = json.loads(resp.choices[0].message.content.strip())
            unique_features = usp_data.get("features", [])
            validated_unique_features = BusinessMetadata(unique_features=unique_features)

            logger.info(
                f"Extracted and validated USPs: {validated_unique_features.unique_features}"
            )
            return validated_unique_features.unique_features

        except Exception as e:
            logger.warning(f"USP extraction failed: {e}")
            return []

    def get_business_details(
        self,
        data_object_id: str,
        access_token: str,
        client_code: str
    ) -> Tuple[str, str]:
        try:
            business_data = connection.fetch_product_details(
                data_object_id, access_token, client_code
            )
            result = business_data[0].get("result", {}).get("result", {})
            scraped_data = result.get("summary", "")
            url = result.get("businessUrl", "")

            logger.info(f"Fetched business details for data_object_id: {data_object_id}")
            return scraped_data, url

        except Exception as e:
            logger.exception(f"Failed to fetch business details: {e}")
            return "", ""  # Return empty strings on failure