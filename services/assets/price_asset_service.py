from exceptions.custom_exceptions import BusinessValidationException
from services.assets.base_asset_service import BaseAssetService
from services.business_service import BusinessService
from utils.text_utils import is_valid_length
from structlog import get_logger

logger = get_logger(__name__)

MAX_HEADER_LENGTH = 25
MAX_DESCRIPTION_LENGTH = 25
DEFAULT_LANGUAGE = "en"
DEFAULT_CURRENCY = "INR"
MIN_PRICE_OFFERINGS = 3


class PriceAssetService(BaseAssetService):
    @staticmethod
    async def generate(
        data_object_id: str,
        access_token: str,
        client_code: str,
        x_forwarded_host: str,
        x_forwarded_port: str,
    ):
        product_data = await BusinessService.fetch_product_details(
            data_object_id,
            access_token,
            client_code,
            x_forwarded_host,
            x_forwarded_port,
        )

        summary = product_data.get("summary", "")
        base_url = product_data.get("businessUrl", "")

        if not base_url or not summary:
            raise BusinessValidationException(
                message="Missing 'summary' or 'businessUrl' for price asset generation",
            )

        # Generate price assets using LLM (expects an array)
        results = await BaseAssetService.generate_from_prompt(
            "price_assets_prompt.txt", {"summary": summary, "base_url": base_url}
        )

        if not results or not isinstance(results, list):
            return []

        formatted_assets = []

        for asset_data in results:
            valid_offerings = []
            currency_code = asset_data.get("currency_code", DEFAULT_CURRENCY)

            # Validate and clean up offerings
            for offer in asset_data.get("price_offerings", []):
                header = offer.get("header", "").strip()
                description = offer.get("description", "").strip()

                # Basic character length validation
                if not is_valid_length(header, MAX_HEADER_LENGTH):
                    continue
                if not is_valid_length(description, MAX_DESCRIPTION_LENGTH):
                    continue

                # Ensure price exists and is valid (positive number)
                price = offer.get("price")
                if price is None or not isinstance(price, (int, float)) or price <= 0:
                    continue

                # Ensure final_url is a single valid URL string
                final_url = offer.get("final_url")
                if not isinstance(final_url, str) or not final_url.strip():
                    final_url = base_url

                valid_offerings.append(
                    {
                        "header": header,
                        "description": description,
                        "final_url": final_url,
                        "price": price,
                        "unit": offer.get("unit", "UNSPECIFIED"),
                    }
                )

            if not valid_offerings:
                continue

            lang = asset_data.get("language_code") or DEFAULT_LANGUAGE

            if len(valid_offerings) < MIN_PRICE_OFFERINGS:
                logger.warning(
                    "Generated fewer than 3 price offerings. This asset may be rejected by Google Ads.",
                    count=len(valid_offerings),
                    data_object_id=data_object_id,
                )

            formatted_assets.append(
                {
                    "type": asset_data.get("type", "SERVICES"),
                    "price_qualifier": asset_data.get("price_qualifier", "FROM"),
                    "language_code": lang,
                    "currency_code": currency_code,
                    "price_offerings": valid_offerings,
                }
            )

        return formatted_assets
