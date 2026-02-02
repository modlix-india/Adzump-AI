from urllib.parse import urlparse


class BrandVisualInterpreterService:

    @staticmethod
    def interpret(brand_assets: dict, scraped_data: dict, website_url: str) -> dict:
        text_blob = " ".join(
            scraped_data.get("paragraphs", []) +
            scraped_data.get("spans", [])
        ).lower()

        brand_name = BrandVisualInterpreterService._extract_brand_name(
            scraped_data, website_url
        )

        # ✅ FIX: read single logo object, not logos list
        logo = brand_assets.get("logo")

        if logo:
            logo_url = logo.get("url")
            logo_confidence = logo.get("confidence", "high")
        else:
            logo_url = None
            logo_confidence = "none"

        brand_type = BrandVisualInterpreterService._detect_brand_type(text_blob)
        visual_style = BrandVisualInterpreterService._detect_visual_style(text_blob)

        visual_intent = BrandVisualInterpreterService._build_visual_intent(
            brand_type=brand_type,
            text_blob=text_blob
        )

        return {
            "brand_name": brand_name,
            "logo_url": logo_url,
            "logo_confidence": logo_confidence,
            "brand_type": brand_type,
            "visual_style": visual_style,

            "preferred_scene_types": visual_intent,
            "ui_focus": False,
            "color_hint": "auto"
        }

    @staticmethod
    def _extract_brand_name(scraped_data: dict, website_url: str) -> str:
        title = scraped_data.get("title")
        if title:
            return title.split("|")[0].strip()

        domain = urlparse(website_url).netloc
        return domain.replace("www.", "").split(".")[0]

    @staticmethod
    def _detect_brand_type(text: str) -> str:
        if any(k in text for k in ["dashboard", "analytics", "ads", "automation"]):
            return "saas"
        if any(k in text for k in ["shop", "order", "buy now", "product"]):
            return "ecommerce"
        if any(k in text for k in ["restaurant", "store", "near you"]):
            return "local_business"
        if any(k in text for k in ["game", "play", "multiplayer", "season"]):
            return "gaming"
        if any(k in text for k in ["car", "drive", "engine", "test drive"]):
            return "automotive"
        return "service"

    @staticmethod
    def _detect_visual_style(text: str) -> str:
        if any(k in text for k in ["luxury", "premium", "exclusive"]):
            return "luxury"
        if any(k in text for k in ["enterprise", "platform", "scale"]):
            return "enterprise"
        if any(k in text for k in ["simple", "easy", "fast"]):
            return "minimal"
        return "modern"

    @staticmethod
    def _build_visual_intent(brand_type: str, text_blob: str) -> list:
        if brand_type == "gaming":
            return [
                "high-energy action scene",
                "dramatic lighting",
                "hero-focused composition",
                "cinematic atmosphere"
            ]

        if brand_type == "automotive":
            return [
                "hero product shot",
                "cinematic environment",
                "motion or power emphasis",
                "premium lighting"
            ]

        if brand_type == "ecommerce":
            return [
                "product-centric composition",
                "studio or lifestyle-neutral background",
                "clean foreground focus",
                "ad-ready framing"
            ]

        if brand_type == "local_business":
            return [
                "real-world service moment",
                "authentic environment",
                "human presence optional",
                "trust-focused composition"
            ]

        if brand_type == "saas":
            return [
                "conceptual success visual",
                "abstract performance metaphor",
                "professional environment",
                "no visible screens"
            ]

        return [
            "brand storytelling scene",
            "clear subject emphasis",
            "negative space for ad text",
            "commercial photography style"
        ]
