from PIL import Image
from io import BytesIO
import tempfile
import os
import uuid
import requests


class MetaCreativeComposer:

    @staticmethod
    def compose(
        background_image_bytes: bytes,
        creative_text: dict,
        layout_config: dict,
        logo: dict | None = None
    ) -> str:

        # 1. Load Gemini image FROM MEMORY
        image = Image.open(BytesIO(background_image_bytes)).convert("RGBA")
        width, height = image.size

        # Normalize logo dict
        logo_data = logo.get("logo") if logo else None

        # 2. Paste logo (SAFE + META-GRADE)
        if logo_data and logo_data.get("confidence", 0) >= 0.6:

            logo_url = logo_data.get("url")
            logo_format = logo_data.get("format", "")

            try:
                # SVG logos are skipped safely (future support optional)
                if logo_format == "svg":
                    raise ValueError("SVG logo skipped (no raster support)")

                response = requests.get(logo_url, timeout=15)
                response.raise_for_status()

                logo_img = Image.open(BytesIO(response.content)).convert("RGBA")

                # Responsive logo sizing (12% of canvas width)
                target_width = int(width * 0.12)
                ratio = target_width / logo_img.width
                logo_img = logo_img.resize(
                    (target_width, int(logo_img.height * ratio)),
                    Image.LANCZOS
                )

                # Contrast backing (Meta safe)
                padding = int(target_width * 0.15)
                bg = Image.new(
                    "RGBA",
                    (logo_img.width + padding * 2, logo_img.height + padding * 2),
                    (0, 0, 0, 160)
                )

                bg.paste(logo_img, (padding, padding), logo_img)

                # Placement (top-left, safe margin)
                image.paste(bg, (40, 40), bg)

            except Exception as e:
                # Silent fail = ad still renders
                pass

        # 3. SAVE FINAL IMAGE
        output_path = os.path.join(
            tempfile.gettempdir(),
            f"meta_ad_creative_{uuid.uuid4().hex}.png"
        )

        image.convert("RGB").save(output_path, quality=95)
        return output_path
