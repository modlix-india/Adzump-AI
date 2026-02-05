import asyncio
import json
from typing import Dict, List, Optional, Set

import structlog
from exceptions.custom_exceptions import (
    AIProcessingException,
    KeywordServiceException,
)
from services.google_kw_update_service import config
from services.openai_client import chat_completion
from third_party.google.models.keyword_model import Keyword
from utils import google_autocomplete, prompt_loader

logger = structlog.get_logger(__name__)


class EnhancedSeedExpander:
    """Multi-layer keyword seed expansion pipeline."""

    async def expand_seed_keywords(
        self,
        good_keywords: List[Keyword],
        business_context: Dict,
    ) -> List[str]:
        """Expand seed keywords using LLM and Google Autocomplete."""
        try:
            logger.info(
                "Starting smart parallel seed expansion",
                good_keyword_count=len(good_keywords),
            )

            # 1. Start LLM and Original Autocomplete tasks concurrently
            original_seeds = [kw.keyword for kw in good_keywords]

            # Fire LLM generation
            llm_task = asyncio.create_task(
                self._generate_llm_seeds(good_keywords, business_context)
            )
            # Fire Autocomplete for keywords we already know (saves ~3-5s)
            auto_original_task = asyncio.create_task(
                self._expand_with_autocomplete(original_seeds)
            )

            # Wait for both primary tasks
            llm_seeds, auto_original_results = await asyncio.gather(
                llm_task, auto_original_task, return_exceptions=True
            )

            # Handle task failures/exceptions
            if isinstance(llm_seeds, Exception):
                logger.error("LLM seed task failed", error=str(llm_seeds))
                llm_seeds = []

            if isinstance(auto_original_results, Exception):
                logger.warning(
                    "Original autocomplete task failed",
                    error=str(auto_original_results),
                )
                auto_original_results = []

            # 2. Identify and expand ONLY the NEW seeds from LLM using the utility
            seen_seeds = {s.lower().strip() for s in original_seeds if s.strip()}
            llm_seeds_list = llm_seeds if isinstance(llm_seeds, list) else []
            new_llm_seeds = self._deduplicate_seeds(llm_seeds_list, seen=seen_seeds)

            auto_llm_results = []
            if new_llm_seeds:
                try:
                    auto_llm_results = await self._expand_with_autocomplete(
                        new_llm_seeds
                    )
                except Exception as e:
                    logger.warning("AI seeds autocomplete failed", error=str(e))

            # 3. Final Merge: Original + AI Seeds + All Autocomplete Results
            all_seeds = list(original_seeds)
            if isinstance(llm_seeds, list):
                all_seeds.extend(llm_seeds)
            if isinstance(auto_original_results, list):
                all_seeds.extend(auto_original_results)
            all_seeds.extend(auto_llm_results)
            final_seeds = self._deduplicate_seeds(all_seeds)

            logger.info(
                "Smart seed expansion complete",
                orig_count=len(original_seeds),
                llm_count=len(llm_seeds_list),
                new_llm_count=len(new_llm_seeds),
                total_expanded=len(final_seeds),
            )

            return final_seeds

        except AIProcessingException:
            raise
        except Exception as e:
            logger.exception("Smart seed expansion failed", error=str(e))
            raise KeywordServiceException(
                message=f"Smart seed expansion failed: {str(e)}",
                details={"error": str(e)},
            )

    async def _generate_llm_seeds(
        self,
        good_keywords: List[Keyword],
        business_context: Dict,
    ) -> List[str]:
        """Generate creative keyword variations using LLM."""
        try:
            logger.info("Generating LLM seed variations")

            # Prepare prompt context
            performing_keywords = ", ".join([kw.keyword for kw in good_keywords[:15]])

            prompt_context = {
                **business_context,
                "performing_keywords": performing_keywords,
                "count": config.LLM_SEED_COUNT,
            }

            # Load and format prompt
            prompt = prompt_loader.format_prompt(
                "seed_expansion_prompt.txt", **prompt_context
            )

            # Call LLM
            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=config.OPENAI_MODEL,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            # Parse and validate
            llm_response = json.loads(response.choices[0].message.content.strip())
            llm_seeds = llm_response.get("keywords", [])

            if not isinstance(llm_seeds, list):
                raise AIProcessingException("LLM response 'keywords' must be a list")

            valid_seeds = [
                s.strip() for s in llm_seeds if isinstance(s, str) and s.strip()
            ]
            logger.info(f"Generated {len(valid_seeds)} variations")
            return valid_seeds

        except (json.JSONDecodeError, AIProcessingException):
            # Re-raise explicit errors or JSON errors with custom details
            raise
        except Exception as e:
            logger.exception("LLM seed generation failed", error=str(e))
            raise AIProcessingException(
                message=f"LLM seed generation failed: {str(e)}",
                details={"error": str(e)},
            )

    async def _expand_with_autocomplete(
        self,
        seed_keywords: List[str],
    ) -> List[str]:
        """Expand seeds using Google Autocomplete."""
        return await google_autocomplete.batch_fetch_autocomplete_suggestions(
            seed_keywords=seed_keywords,
            max_results_per_seed=config.AUTOCOMPLETE_MAX_SUGGESTIONS,
        )

    def _deduplicate_seeds(
        self, seeds: List[str], seen: Optional[Set[str]] = None
    ) -> List[str]:
        """Remove duplicates while preserving order."""
        if seen is None:
            seen = set()

        unique_seeds = []
        for seed in seeds:
            seed_lower = seed.lower().strip()
            if seed_lower and seed_lower not in seen:
                seen.add(seed_lower)
                unique_seeds.append(seed)
        return unique_seeds
