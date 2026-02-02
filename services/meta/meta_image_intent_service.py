from fastapi import HTTPException
from services.genai_client import text_completion
from utils.prompt_loader import load_prompt

IMAGE_INTENT_PROMPT = load_prompt("meta/meta_image_intent_prompt.txt")


class MetaImageIntentService:

    @staticmethod
    async def generate_image_prompt(
        summary: str,
        strategy: dict | None = None,
        brand_context: dict | None = None
    ) -> str:
        """
        Generates a BRAND-SAFE, POSTER-STYLE visual-only image prompt.
        Output is a single descriptive string suitable for image generation models.
        """

        # --------- CHANGE 1: Extract only what visuals need (not raw dicts) ---------
        brand_type = (brand_context or {}).get("brand_type", "service")
        visual_style = (brand_context or {}).get("visual_style", "modern")
        scene_types = (brand_context or {}).get("preferred_scene_types", [])

        layout = (strategy or {}).get("layout_config", {})
        text_position = layout.get("text_position", "bottom")

        # --------- CHANGE 2: Build a strict visual directive ---------
        visual_directive = (
            f"Brand Type: {brand_type}\n"
            f"Visual Style: {visual_style}\n"
            f"Preferred Scenes: {', '.join(scene_types) if scene_types else 'General'}\n"
            f"Layout Context: {text_position} aligned text"
        )

        # --------- CHANGE 3: Feed structured visual intent to prompt ---------
        prompt = IMAGE_INTENT_PROMPT.format(
            summary=summary,
            visual_directive=visual_directive
        )

        try:
            visual_prompt = await text_completion(prompt)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate image prompt: {str(e)}"
            )

        if not visual_prompt or not visual_prompt.strip():
            raise HTTPException(
                status_code=500,
                detail="Empty image prompt returned from image intent generation"
            )

        # --------- CHANGE 4: Final safety clamp ---------
        return (
    visual_prompt.strip()
    + "\n\n"
    + "STRICT CONSTRAINTS:\n"
      "- Background image only\n"
      "- No logos, brand marks, or watermarks\n"
      "- No readable text or typography\n"
      "- No UI screens, dashboards, or app interfaces\n"
      "- No buttons, CTAs, or labels\n"
      "- No brand colors or brand identity elements\n"
      "- Suitable as a Meta ad background image"
)
