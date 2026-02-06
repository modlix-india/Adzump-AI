import json
import asyncio
from functools import cache
from structlog import get_logger

from services.openai_client import chat_completion
from services.json_utils import safe_json_parse
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)

PROMPT_DIR = "optimization/search_term"

MATCH_LEVEL_TO_STRENGTH = {
    "Perfect Match": "STRONG",
    "Strong Match": "STRONG",
    "Moderate Match": "MEDIUM",
    "Medium Match": "MEDIUM",
    "Partial Match": "MEDIUM",
    "Weak Match": "LOW",
    "No Match": "LOW",
}


@cache
def _load_prompt(file_name: str) -> str:
    return load_prompt(f"{PROMPT_DIR}/{file_name}")


class SearchTermAnalyzer:
    MODEL = "gpt-4o-mini"

    async def analyze_term(self, summary: str, search_term: str, metrics: dict) -> dict:
        """Run all relevancy checks for a single search term."""
        brand_result = await self._check_relevancy(summary, search_term, "brand")
        brand_type = brand_result.get("brand", {}).get("type", "generic")

        config_result, location_result = await asyncio.gather(
            self._check_relevancy(summary, search_term, "configuration"),
            self._check_location(summary, search_term, brand_type),
        )

        brand_match = brand_result.get("brand", {}).get("match", False)
        config_match = config_result.get("configuration", {}).get("match", False)

        if not brand_match and not config_match:
            overall_result = {
                "overall": {
                    "match": False,
                    "match_level": "No Match",
                    "intent_stage": "Irrelevant",
                    "suggestion_type": "negative",
                    "reason": "No brand, configuration, or location match.",
                }
            }
        else:
            overall_result = await self._check_overall(
                summary, search_term, brand_result, config_result, location_result
            )

        overall = overall_result.get("overall", {})
        suggestion_type = str(overall.get("suggestion_type", "negative"))
        match_level = str(overall.get("match_level", "No Match"))

        return {
            "text": search_term,
            "recommendation": "ADD",
            "recommendation_type": "positive" if suggestion_type == "positive" else "negative",
            "reason": str(overall.get("reason", "")),
            "source": "SEARCH_TERM",
            "metrics": metrics,
            "analysis": {
                "brand": brand_result.get("brand", {}),
                "configuration": config_result.get("configuration", {}),
                "location": location_result.get("location", {}),
                "strength": MATCH_LEVEL_TO_STRENGTH.get(match_level, "LOW"),
            },
        }

    async def _check_relevancy(
        self, summary: str, search_term: str, check_type: str
    ) -> dict:
        system_msg = _load_prompt(f"{check_type}_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"
        return await self._call_llm(system_msg, user_msg, check_type)

    async def _check_location(
        self, summary: str, search_term: str, brand_type: str
    ) -> dict:
        if brand_type == "competitor":
            return {
                "location": {
                    "match": False,
                    "type": "skipped_due_to_competitor",
                    "match_level": "No Match",
                    "reason": "Search term contains a competitor brand.",
                }
            }
        return await self._check_relevancy(summary, search_term, "location")

    async def _check_overall(
        self,
        summary: str,
        search_term: str,
        brand_result: dict,
        config_result: dict,
        location_result: dict,
    ) -> dict:
        system_msg = _load_prompt("overall_relevancy_prompt.txt")
        user_msg = (
            f"PROJECT SUMMARY:{summary}\n"
            f"SEARCH TERM:{search_term}\n"
            f"BRAND:{json.dumps(brand_result)}\n"
            f"CONFIG:{json.dumps(config_result)}\n"
            f"LOCATION:{json.dumps(location_result)}"
        )
        return await self._call_llm(system_msg, user_msg, "overall")

    async def _call_llm(self, system_msg: str, user_msg: str, label: str) -> dict:
        try:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            response = await chat_completion(messages, model=self.MODEL)
            content = (
                response.choices[0].message.content.strip() if response.choices else ""
            )
            parsed = safe_json_parse(content)
            if not parsed or "error" in parsed:
                logger.error("LLM JSON parsing failed", label=label)
                return {}
            return parsed
        except Exception as e:
            logger.exception("LLM call failed", label=label, error=str(e))
            return {}

