import asyncio
import json
from enum import Enum
from typing import List, Dict, Any
from structlog import get_logger

from pydantic import ValidationError
from core.infrastructure.context import auth_context
from core.models.meta import (
    TargetingSeedsResponse,
    TargetingFilterResponse,
    TargetingCategory,
)
from utils.prompt_loader import format_prompt
from agents.shared.llm import chat_completion
from adapters.meta.client import meta_client

logger = get_logger(__name__)


class CategorySeedPrompt(str, Enum):
    INTERESTS = "meta/interest_suggestions.txt"
    DEMOGRAPHICS = "meta/demographics_suggestions.txt"
    BEHAVIORS = "meta/behaviours_suggestions.txt"


class MetaTargetingExecutor:
    OPENAI_MODEL = "gpt-4o-mini"

    DEFAULT_META_LIMIT = 500
    DEFAULT_META_CONCURRENCY = 10

    DEFAULT_LLM_BATCH_SIZE = 30
    DEFAULT_LLM_MAX_CONCURRENT = 5
    DEFAULT_LLM_MAX_RETRIES = 2
    DEFAULT_LLM_TIMEOUT = 20

    FILTER_PROMPT_PATH = "meta/detailed_targeting_analysis.txt"

    def __init__(
        self,
        ad_account_id: str,
        *,
        meta_limit: int = DEFAULT_META_LIMIT,
        meta_concurrency: int = DEFAULT_META_CONCURRENCY,
        llm_batch_size: int = DEFAULT_LLM_BATCH_SIZE,
        llm_max_concurrent: int = DEFAULT_LLM_MAX_CONCURRENT,
        llm_max_retries: int = DEFAULT_LLM_MAX_RETRIES,
        llm_timeout: int = DEFAULT_LLM_TIMEOUT,
    ) -> None:

        self.ad_account_id = ad_account_id

        # Meta config
        self.meta_limit = meta_limit
        self.meta_semaphore = asyncio.Semaphore(meta_concurrency)

        # LLM config
        self.llm_batch_size = llm_batch_size
        self.llm_max_concurrent = llm_max_concurrent
        self.llm_max_retries = llm_max_retries
        self.llm_timeout = llm_timeout
        self.llm_semaphore = asyncio.Semaphore(llm_max_concurrent)

    # PIPELINE
    async def run_targeting_pipeline(
        self,
        category: TargetingCategory,
        business_summary: str,
    ) -> List[Dict[str, Any]]:

        if not isinstance(category, TargetingCategory):
            try:
                category = TargetingCategory(category)
            except ValueError:
                raise ValueError(f"Invalid category: {category}")

        seeds = await self._generate_seed_suggestions(category, business_summary)

        if not seeds:
            logger.warning(
                f"No seeds generated for category {category}, skipping pipeline."
            )
            return []

        raw_candidates = await self._fetch_meta_targeting_results_for_seeds(
            category, seeds
        )

        if not raw_candidates:
            logger.warning(
                f"No raw candidates fetched from Meta APIs for category {category}."
            )
            return []

        category_filtered = self._filter_by_targeting_category(raw_candidates, category)

        unique_candidates = self._deduplicate_targeting_entities(category_filtered)

        final_results = await self._select_relevant_candidates_via_llm(
            category, business_summary, unique_candidates
        )

        return final_results

    # SEED GENERATION
    async def _generate_seed_suggestions(
        self,
        category: TargetingCategory,
        business_summary: str,
    ) -> List[str]:

        prompt_file = CategorySeedPrompt[category.name].value
        prompt = format_prompt(prompt_file, summary=business_summary)

        try:
            response = await chat_completion(
                [
                    {"role": "system", "content": "Respond only with valid JSON"},
                    {"role": "user", "content": prompt},
                ],
                model=self.OPENAI_MODEL,
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            raw_output = response.choices[0].message.content

            if not raw_output:
                logger.warning(f"Empty seed response from LLM for category {category}")
                return []

            parsed = TargetingSeedsResponse.model_validate_json(raw_output)
            if not parsed.seeds:
                logger.warning(
                    f"No seeds found in valid JSON response for category {category}"
                )
                return []

            return parsed.seeds

        except ValidationError as e:
            logger.warning(f"Invalid seed JSON for category {category}: {e}")
            return []
        except Exception as e:
            logger.exception(f"Seed generation failed for category {category}: {e}")
            return []

    # META FETCH
    async def _fetch_meta_targeting_results_for_seeds(
        self,
        category: TargetingCategory,
        seeds: List[str],
    ) -> List[Dict[str, Any]]:

        search_type = TargetingCategory[category.name].value

        async def fetch(seed: str):
            async with self.meta_semaphore:
                return await self._fetch_meta_targeting_results(search_type, seed)

        results = await asyncio.gather(
            *[fetch(seed) for seed in seeds],
            return_exceptions=True,
        )

        aggregated = []

        for seed, result in zip(seeds, results):
            if isinstance(result, Exception):
                logger.warning("seed_fetch_failed", seed=seed)
                continue
            aggregated.extend(result)

        return aggregated

    async def _fetch_meta_targeting_results(
        self,
        search_type: str,
        query: str,
    ) -> List[Dict[str, Any]]:

        account_id = self._normalize_ad_account_id(self.ad_account_id)

        params = {
            "q": query,
            "limit": self.meta_limit,
        }

        if search_type != "demographics":
            params["limit_type"] = search_type

        response = await meta_client.get(
            f"/act_{account_id}/targetingsearch",
            client_code=auth_context.client_code,
            params=params,
        )

        return response.get("data", [])

    # CATEGORY FILTER
    def _filter_by_targeting_category(
        self,
        raw_items: List[Dict[str, Any]],
        category: TargetingCategory,
    ) -> List[Dict[str, Any]]:

        if category in {TargetingCategory.INTERESTS, TargetingCategory.BEHAVIORS}:
            return [item for item in raw_items if item.get("type") == category.value]

        if category == TargetingCategory.DEMOGRAPHICS:
            return [
                item
                for item in raw_items
                if item.get("type")
                not in {
                    TargetingCategory.INTERESTS.value,
                    TargetingCategory.BEHAVIORS.value,
                }
            ]

        return []

    # DEDUPLICATION
    def _deduplicate_targeting_entities(
        self,
        raw_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        seen_ids = set()
        unique = []

        for item in raw_items:
            item_id = str(item.get("id", ""))
            if not item_id or item_id in seen_ids:
                continue

            seen_ids.add(item_id)
            unique.append(item)

        return unique

    # LLM FILTER (BATCHED)
    async def _select_relevant_candidates_via_llm(
        self,
        category: TargetingCategory,
        business_summary: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        if not candidates:
            return []

        # Sort for better quality
        candidates = sorted(
            candidates,
            key=lambda x: x.get("audience_size", 0),
            reverse=True,
        )

        batches = [
            candidates[i : i + self.llm_batch_size]
            for i in range(0, len(candidates), self.llm_batch_size)
        ]

        async def process_batch(batch, idx):
            async with self.llm_semaphore:
                valid_ids = {item["id"] for item in batch}

                payload = json.dumps(
                    [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "type": item.get("type"),
                        }
                        for item in batch
                    ],
                    separators=(",", ":"),
                )

                prompt = format_prompt(
                    self.FILTER_PROMPT_PATH,
                    summary=business_summary,
                    category=category,
                    candidates=payload,
                )

                for attempt in range(self.llm_max_retries):
                    try:
                        response = await asyncio.wait_for(
                            chat_completion(
                                [
                                    {
                                        "role": "system",
                                        "content": "Respond only with valid JSON",
                                    },
                                    {"role": "user", "content": prompt},
                                ],
                                model=self.OPENAI_MODEL,
                                temperature=0.0,
                                response_format={"type": "json_object"},
                            ),
                            timeout=self.llm_timeout,
                        )

                        parsed = TargetingFilterResponse.model_validate_json(
                            response.choices[0].message.content
                        )

                        return [_id for _id in parsed.selected_ids if _id in valid_ids]

                    except Exception as e:
                        logger.warning(
                            "batch_retry",
                            batch_index=idx,
                            attempt=attempt,
                            error=str(e),
                        )

                        if attempt == self.llm_max_retries - 1:
                            return []

        results = await asyncio.gather(
            *[process_batch(batch, i) for i, batch in enumerate(batches)],
            return_exceptions=True,
        )

        selected_ids = set()

        for result in results:
            if isinstance(result, Exception):
                continue
            selected_ids.update(result)

        return [item for item in candidates if item.get("id") in selected_ids]

    # UTIL
    @staticmethod
    def _normalize_ad_account_id(ad_account_id: str) -> str:
        return ad_account_id.replace("act_", "")
