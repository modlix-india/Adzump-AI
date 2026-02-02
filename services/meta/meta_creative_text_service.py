import json
from fastapi import HTTPException
from services.genai_client import text_completion
from utils.prompt_loader import load_prompt

STRATEGY_PROMPT = load_prompt("meta/meta_creative_strategy_prompt.txt")
CREATIVE_TEXT_PROMPT = load_prompt("meta/meta_creative_text_prompt.txt")


class MetaCreativeTextService:

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return text[start : end + 1]
        return text

    @staticmethod
    async def generate_creative_text(summary: str) -> dict:
        strategy_prompt = STRATEGY_PROMPT.format(summary=summary)

        strategy_response = await text_completion(strategy_prompt)
        strategy_raw = MetaCreativeTextService._extract_json(strategy_response)

        try:
            strategy = json.loads(strategy_raw)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Invalid creative strategy JSON"
            )

        # -------- CHANGE 1: Enforce poster-style strategy --------
        strategy.setdefault("ad_format", "poster")
        strategy.setdefault("creative_density", "low")

        required_strategy_keys = {
            "creative_type",
            "goal",
            "visual_focus",
            "layout_config",
            "ad_format",
            "creative_density"
        }

        if not required_strategy_keys.issubset(strategy.keys()):
            raise HTTPException(
                status_code=500,
                detail="Creative strategy missing required fields"
            )

        creative_text_prompt = CREATIVE_TEXT_PROMPT.format(
            summary=summary,
            strategy=json.dumps(strategy)
        )

        creative_text_response = await text_completion(creative_text_prompt)
        creative_text_raw = MetaCreativeTextService._extract_json(creative_text_response)

        try:
            creative_text = json.loads(creative_text_raw)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Invalid creative text JSON"
            )

        # -------- CHANGE 2: Reduce text surface for brand ads --------
        required_text_keys = {
            "headline",
            "cta"
        }

        if not required_text_keys.issubset(creative_text.keys()):
            raise HTTPException(
                status_code=500,
                detail="Creative text missing required headline or CTA"
            )

        # -------- CHANGE 3: Normalize optional fields --------
        creative_text.setdefault("badge", "")
        creative_text.setdefault("features", [])
        creative_text.setdefault("primary_text", "")

        # -------- CHANGE 4: Hard cap features to avoid clutter --------
        if isinstance(creative_text.get("features"), list):
            creative_text["features"] = creative_text["features"][:3]

        # -------- CHANGE 5: Enforce headline dominance --------
        creative_text["headline"] = creative_text["headline"].strip()

        return {
            "strategy": strategy,
            "creative_text": creative_text
        }
