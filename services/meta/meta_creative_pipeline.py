from services.meta.meta_creative_text_service import MetaCreativeTextService
from services.meta.meta_image_intent_service import MetaImageIntentService
from services.meta.meta_ad_image_service import MetaAdImageService
from services.meta.meta_creative_composer import MetaCreativeComposer
from services.business_service import BusinessService
from services.meta.meta_brand_visual_interpreter import BrandVisualInterpreterService
from services.meta.brand_asset_scraper import BrandAssetScraper


class MetaCreativePipeline:

    @staticmethod
    async def generate_creative(
        data_object_id: str,
        access_token: str,
        client_code: str,
        logo_url: str | None = None,
        x_forwarded_host: str | None = None,
        x_forwarded_port: str | None = None,
    ):
        # -------------------------------------------------
        # 1. Fetch business/product data
        # -------------------------------------------------
        product_data = await BusinessService.fetch_product_details(
            data_object_id,
            access_token,
            client_code,
            x_forwarded_host,
            x_forwarded_port
        )

        summary = product_data.get("summary")
        website_url = product_data.get("website_url") or product_data.get("businessUrl")

        if not summary or not website_url:
            raise ValueError(
                f"Missing summary or website_url (found keys: {list(product_data.keys())})"
            )

        # -------------------------------------------------
        # 2. Scrape brand assets (logo)
        # -------------------------------------------------
        brand_assets = await BrandAssetScraper.extract_assets(website_url) or {}
        scraped_logo = brand_assets  # IMPORTANT FIX

        # -------------------------------------------------
        # 3. Build brand visual context
        # -------------------------------------------------
        brand_context = BrandVisualInterpreterService.interpret(
            brand_assets=brand_assets,
            scraped_data=product_data,
            website_url=website_url
        )

        # -------------------------------------------------
        # 4. Generate creative text
        # -------------------------------------------------
        text_result = await MetaCreativeTextService.generate_creative_text(summary)

        if not text_result or not text_result.get("creative_text"):
            raise ValueError("Creative text generation failed")

        strategy = text_result["strategy"]
        creative_text = text_result["creative_text"]

        # -------------------------------------------------
        # 5. Generate image intent
        # -------------------------------------------------
        image_prompt = await MetaImageIntentService.generate_image_prompt(
            summary=summary,
            strategy=strategy,
            brand_context=brand_context
        )

        if not image_prompt:
            raise ValueError("Image intent generation failed")

        # -------------------------------------------------
        # 6. Generate base image (BYTES / BASE64)
        # -------------------------------------------------
        image_bytes = await MetaAdImageService.generate_image(image_prompt)

        if not image_bytes:
            raise ValueError("Image generation failed")

        # -------------------------------------------------
        # 7. Final logo decision (override > scraped)
        # -------------------------------------------------
        if logo_url:
            ext = os.path.splitext(logo_url)[1].replace(".", "").lower()
            final_logo = {
                "logo": {
                    "url": logo_url,
                    "confidence": 1.0,
                    "source": "override",
                    "format": ext or "unknown"
                }
            }
        else:
            final_logo = scraped_logo

        # -------------------------------------------------
        # 8. Compose final creative (ONE FINAL IMAGE)
        # -------------------------------------------------
        final_image_path = MetaCreativeComposer.compose(
            background_image_bytes=image_bytes,
            creative_text=creative_text,
            layout_config=strategy["layout_config"],
            logo=final_logo
        )

        return {
            "strategy": strategy,
            "creative_text": creative_text,
            "image_intent": image_prompt,
            "final_image": final_image_path,
            "logo": final_logo
        }
