import asyncio
import json

import structlog

from services.openai_client import chat_completion
from utils.google_autocomplete import batch_fetch_autocomplete_suggestions
from utils.prompt_loader import load_prompt

logger = structlog.get_logger(__name__)

LLM_SEED_COUNT = 10
AUTOCOMPLETE_MAX_SUGGESTIONS = 5


class KeywordSeedExpander:
    async def expand_seeds(
        self,
        good_keywords: list[str],
        business_type: str,
        primary_location: str,
        features_context: str,
    ) -> list[str]:
        original_seeds = self._deduplicate(good_keywords)

        llm_seeds, autocomplete_from_originals = await asyncio.gather(
            self._generate_llm_seeds(
                original_seeds, business_type, primary_location, features_context
            ),
            self._expand_with_autocomplete(original_seeds),
        )

        seen = {s.lower() for s in original_seeds}
        new_llm_seeds = self._deduplicate(llm_seeds, seen)

        autocomplete_from_llm = await self._expand_with_autocomplete(new_llm_seeds)

        all_seeds = (
            original_seeds
            + new_llm_seeds
            + autocomplete_from_originals
            + autocomplete_from_llm
        )
        return self._deduplicate(all_seeds)

    async def _generate_llm_seeds(
        self,
        performing_keywords: list[str],
        business_type: str,
        primary_location: str,
        features_context: str,
    ) -> list[str]:
        try:
            template = load_prompt("seed_expansion_prompt.txt")
            keywords_text = ", ".join(performing_keywords[:15])
            fc = f"- Unique Features: {features_context}" if features_context else ""
            prompt = template.format(
                performing_keywords=keywords_text,
                business_type=business_type,
                primary_location=primary_location,
                features_context=fc,
                count=LLM_SEED_COUNT,
            )

            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            data = json.loads(response.choices[0].message.content)
            seeds = data.get("keywords", [])
            logger.info("LLM seed generation complete", count=len(seeds))
            return seeds
        except Exception as e:
            logger.error("LLM seed generation failed", error=str(e))
            return []

    async def _expand_with_autocomplete(self, seeds: list[str]) -> list[str]:
        if not seeds:
            return []
        return await batch_fetch_autocomplete_suggestions(
            seeds, max_results_per_seed=AUTOCOMPLETE_MAX_SUGGESTIONS
        )

    # TODO: Move to utils/text_utils.py as deduplicate_strings().
    # Same pattern exists in google_autocomplete.py and keyword_utils.py.
    def _deduplicate(self, seeds: list[str], seen: set[str] | None = None) -> list[str]:
        seen = set(seen) if seen else set()
        unique = []
        for s in seeds:
            key = s.lower().strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(s)
        return unique


seed_expander = KeywordSeedExpander()
