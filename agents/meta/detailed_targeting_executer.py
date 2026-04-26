import asyncio
import json

import structlog
from pydantic import ValidationError

from adapters.meta.client import meta_client
from agents.shared.llm import chat_completion
from core.infrastructure.context import auth_context
from core.models.meta import (
    TargetingSeedsResponse,
    TargetingFilterResponse,
    TargetingCategory,
    TargetingEntity,
)
from exceptions.custom_exceptions import (
    BaseAppException,
    BusinessValidationException,
    AIProcessingException,
    MetaAPIException,
)
from utils.prompt_loader import format_prompt


logger = structlog.get_logger(__name__)

# OpenAI models
SEED_MODEL = "gpt-4o-mini"
FILTER_MODEL = "gpt-4o"

# Constants
FILTER_PROMPT_PATH = "meta/detailed_targeting_analysis.txt"

# Meta API Constants
META_LIMIT = 500
META_FETCH_TIMEOUT = 15.0
META_MAX_ATTEMPTS = 2  # First attempt + 1 retry
# LLM Constants
LLM_BATCH_SIZE = 30
LLM_MAX_ATTEMPTS = 3  # First attempt + 2 retries
LLM_TIMEOUT = 35

# Global semaphores to ensure cross-request rate limiting
META_SEMAPHORE = asyncio.Semaphore(10)
LLM_SEMAPHORE = asyncio.Semaphore(5)

# Mapping categories to their seed generation prompts
CATEGORY_SEED_PROMPTS = {
    TargetingCategory.INTERESTS: "meta/interest_suggestions.txt",
    TargetingCategory.DEMOGRAPHICS: "meta/demographics_suggestions.txt",
    TargetingCategory.BEHAVIORS: "meta/behaviors_suggestions.txt",
}

# Category-specific truncation limits (Maximum Rule)
CATEGORY_LIMITS = {
    TargetingCategory.INTERESTS: 20,
    TargetingCategory.DEMOGRAPHICS: 10,
    TargetingCategory.BEHAVIORS: 15,
}


class MetaTargetingExecutor:
    """
    Stateless singleton executor for Meta targeting pipelines.
    Handles parallel API fetching, LLM-based filtering, and result normalization.
    """

    async def run_targeting_pipeline(
        self,
        ad_account_id: str,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[TargetingEntity]:
        """Execute the full targeting pipeline for a specific category."""

        # 1. Validate category before binding context
        try:
            category = TargetingCategory(category)
        except (ValueError, TypeError):
            raise BusinessValidationException(f"Invalid targeting category: {category}")

        # Bind category context as early as possible for uniform logging
        structlog.contextvars.bind_contextvars(category=str(category))

        try:
            # 2. Normalize account ID once at the entry point
            account_id = self._normalize_ad_account_id(ad_account_id)
            # 3. Generate Seeds
            seeds = await self._generate_seed_suggestions(category, business_summary)
            if not seeds:
                logger.warning("meta_detailed_targeting.seeds.missing")
                return []

            # 4. Diversify Seeds (Semantic Deduplication)
            diverse_seeds = self._diversify_seeds(seeds)
            logger.info(
                "meta_detailed_targeting.seeds.diversified",
                original_count=len(seeds),
                diverse_count=len(diverse_seeds),
            )

            # 5. Fetch Candidates
            raw_candidates = await self._fetch_meta_targeting_candidates(
                account_id, category, diverse_seeds
            )
            if not raw_candidates:
                logger.warning("meta_detailed_targeting.candidates.missing")
                return []

            # 6. Filter and Deduplicate
            category_filtered = self._filter_targeting_by_category(
                raw_candidates, category
            )
            unique_candidates = self._deduplicate_targeting_entities(category_filtered)

            # 7. Select Relevant Candidates
            final_results = await self._select_relevant_candidates_using_llm(
                category, business_summary, unique_candidates
            )

            # 8. Truncate for Quality (Maximum Rule)
            # Apply category-specific limits to ensure high relevance
            limit = CATEGORY_LIMITS.get(category, 15)
            final_results = final_results[:limit]

            logger.info(
                "meta_detailed_targeting.pipeline.complete",
                result_count=len(final_results),
            )

            return final_results

        except BaseAppException:
            raise
        except Exception:
            logger.exception("meta_detailed_targeting.pipeline.failed")
            raise AIProcessingException(
                f"Targeting pipeline failed for {category.value}"
            )
        finally:
            # Unbind only the category context, leaving session/account IDs intact
            structlog.contextvars.unbind_contextvars("category")

    async def _generate_seed_suggestions(
        self,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[str]:
        """Generate seed keywords for the provided category using LLM analysis."""
        prompt_file = CATEGORY_SEED_PROMPTS.get(category)
        if not prompt_file:
            logger.error("meta_detailed_targeting.config.missing_prompt")
            return []

        prompt = format_prompt(prompt_file, summary=business_summary)

        try:
            response = await chat_completion(
                [
                    {
                        "role": "system",
                        "content": "You are a search strategist for Meta Ads audience discovery. Your task is to generate specific, targeted search queries that will surface the most relevant audience segments for this business when run against Meta's targeting API.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=SEED_MODEL,
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            if not response.choices:
                logger.error("meta_detailed_targeting.llm.no_choices")
                return []

            raw_output = response.choices[0].message.content
            if not raw_output:
                logger.warning("meta_detailed_targeting.llm.empty_output")
                return []

            parsed = TargetingSeedsResponse.model_validate_json(raw_output)
            if not parsed.seeds:
                logger.warning("meta_detailed_targeting.llm.no_seeds_in_json")
                return []

            return parsed.seeds

        except ValidationError as error:
            logger.warning(
                "meta_detailed_targeting.seeds.validation_failed",
                error=str(error),
            )
            return []
        except Exception as error:
            logger.exception("meta_detailed_targeting.seeds.error")
            raise AIProcessingException(
                message=f"Failed to generate seeds for {category.value}",
                details={"error": str(error)},
            )

    async def _fetch_meta_targeting_candidates(
        self,
        ad_account_id: str,
        category: TargetingCategory,
        seeds: list[str],
    ) -> list[TargetingEntity]:
        """Fetch targeting candidates from Meta in parallel for multiple seeds."""
        search_type = category.value

        async def fetch(seed: str):
            """Fetch results for a single seed with retry logic."""
            for attempt in range(META_MAX_ATTEMPTS):
                try:
                    async with META_SEMAPHORE:
                        return await asyncio.wait_for(
                            self._fetch_meta_targeting_results(
                                ad_account_id, search_type, seed
                            ),
                            timeout=META_FETCH_TIMEOUT,
                        )
                except Exception as error:
                    # Retry on first attempt, raise on subsequent failures
                    if attempt < META_MAX_ATTEMPTS - 1:
                        logger.warning(
                            "meta_detailed_targeting.api.retry",
                            seed=seed,
                            attempt=attempt + 1,
                            error=str(error),
                        )
                        await asyncio.sleep(2**attempt)
                        continue
                    raise

        results = await asyncio.gather(
            *[fetch(seed) for seed in seeds],
            return_exceptions=True,
        )

        aggregated = []
        for seed, result in zip(seeds, results):
            if isinstance(result, Exception):
                logger.warning(
                    "meta_detailed_targeting.api.fetch_failed",
                    seed=seed,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            aggregated.extend(result)

        return aggregated

    async def _fetch_meta_targeting_results(
        self,
        ad_account_id: str,
        search_type: str,
        query: str,
    ) -> list[TargetingEntity]:
        """Fetch targeting results from Meta for a single query string."""
        params = {
            "q": query,
            "limit": META_LIMIT,
        }

        # Meta API defaults to demographics if limit_type is omitted
        if search_type != "demographics":
            params["limit_type"] = search_type

        response = await meta_client.get(
            f"/act_{ad_account_id}/targetingsearch",
            client_code=auth_context.client_code,
            params=params,
        )

        if "error" in response:
            error_msg = response["error"].get("message") or str(response["error"])
            logger.error(
                "meta_detailed_targeting.api.error_response",
                error=error_msg,
                query=query,
            )
            raise MetaAPIException(f"Meta API error: {error_msg}")

        return [
            TargetingEntity.model_validate(item) for item in response.get("data", [])
        ]

    def _filter_targeting_by_category(
        self,
        raw_items: list[TargetingEntity],
        category: TargetingCategory,
    ) -> list[TargetingEntity]:
        """Filter raw Meta results to match the requested TargetingCategory."""
        before_count = len(raw_items)
        target_value = category.value.lower()

        if category in {TargetingCategory.INTERESTS, TargetingCategory.BEHAVIORS}:
            filtered_results = [
                item for item in raw_items if str(item.type).lower() == target_value
            ]
        elif category == TargetingCategory.DEMOGRAPHICS:
            filtered_results = [
                item
                for item in raw_items
                if str(item.type).lower()
                not in {
                    TargetingCategory.INTERESTS.value.lower(),
                    TargetingCategory.BEHAVIORS.value.lower(),
                }
            ]
        else:
            filtered_results = []

        logger.info(
            "meta_detailed_targeting.filter.complete",
            before=before_count,
            after=len(filtered_results),
        )

        return filtered_results

    async def _select_relevant_candidates_using_llm(
        self,
        category: TargetingCategory,
        business_summary: str,
        candidates: list[TargetingEntity],
    ) -> list[TargetingEntity]:
        """Coordinate batched LLM calls to filter for the most relevant candidates."""
        if not candidates:
            return []

        # 1. Batch in original Meta order (preserves Meta's relevance ranking)
        batches = [
            candidates[i : i + LLM_BATCH_SIZE]
            for i in range(0, len(candidates), LLM_BATCH_SIZE)
        ]

        # 2. Concurrency: Run parallel LLM filters
        tasks = [
            self._process_llm_filter_batch(
                batch, batch_index, category, business_summary
            )
            for batch_index, batch in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. Consolidation: Collect selected IDs
        selected_ids = set()
        for result in results:
            if isinstance(result, list):
                selected_ids.update(str(result_id) for result_id in result)
            elif isinstance(result, Exception):
                logger.error("meta_detailed_targeting.batch.failed", error=str(result))

        # 4. Final Sort: Sort survivors by audience size
        final_results = [
            candidate for candidate in candidates if str(candidate.id) in selected_ids
        ]
        return sorted(
            final_results,
            key=lambda candidate: getattr(candidate, "audience_size", 0) or 0,
            reverse=True,
        )

    async def _process_llm_filter_batch(
        self,
        batch: list[TargetingEntity],
        batch_index: int,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[str]:
        """Filter a single batch of candidates using LLM with retry logic."""
        valid_ids = {str(item.id) for item in batch if item.id}
        prompt = format_prompt(
            FILTER_PROMPT_PATH,
            summary=business_summary,
            category=category.value,
            candidates=json.dumps(
                [
                    {"id": str(item.id), "name": item.name, "type": item.type}
                    for item in batch
                ],
                separators=(",", ":"),
            ),
        )

        for attempt in range(LLM_MAX_ATTEMPTS):
            try:
                async with LLM_SEMAPHORE:
                    response = await asyncio.wait_for(
                        chat_completion(
                            [
                                {
                                    "role": "system",
                                    "content": "You are a ruthless Meta Ads relevance filter. Your default is to reject. Only keep candidates with a clear, direct, defensible connection to this specific business and buyer. Uncertain = reject.",
                                },
                                {"role": "user", "content": prompt},
                            ],
                            model=FILTER_MODEL,
                            temperature=0.0,
                            response_format={"type": "json_object"},
                        ),
                        timeout=LLM_TIMEOUT,
                    )

                    parsed = TargetingFilterResponse.model_validate_json(
                        response.choices[0].message.content
                    )
                    return [
                        str(selected_id)
                        for selected_id in parsed.selected_ids
                        if str(selected_id) in valid_ids
                    ]

            except asyncio.TimeoutError:
                logger.warning(
                    "meta_detailed_targeting.batch.timeout",
                    batch_idx=batch_index,
                    attempt=attempt,
                )
                if attempt == LLM_MAX_ATTEMPTS - 1:
                    logger.error(
                        "meta_detailed_targeting.batch.lost_to_timeout",
                        batch_idx=batch_index,
                    )
                    return []
            except Exception as error:
                logger.warning(
                    "meta_detailed_targeting.batch.error",
                    batch_idx=batch_index,
                    attempt=attempt,
                    error=str(error),
                )
                if attempt == LLM_MAX_ATTEMPTS - 1:
                    logger.error(
                        "meta_detailed_targeting.batch.lost_to_error",
                        batch_idx=batch_index,
                        error=str(error),
                    )
                    return []

            # Exponential backoff
            if attempt < LLM_MAX_ATTEMPTS - 1:
                await asyncio.sleep(2**attempt)

        return []

    @staticmethod
    def _diversify_seeds(seeds: list[str]) -> list[str]:
        """
        Remove seeds that are semantically too similar to an already selected seed.
        Uses a simple word-overlap ratio to identify variations of the same concept.
        """
        selected: list[str] = []
        for seed in seeds:
            seed_words = set(seed.lower().split())
            if not seed_words:
                continue

            # Check overlap with already selected seeds
            is_redundant = False
            for selected_seed in selected:
                selected_words = set(selected_seed.lower().split())
                overlap = len(seed_words & selected_words)
                ratio = overlap / max(len(seed_words), len(selected_words))

                # If more than 60% of words overlap, consider it a duplicate concept
                if ratio > 0.6:
                    is_redundant = True
                    break

            if not is_redundant:
                selected.append(seed)

        return selected

    @staticmethod
    def _deduplicate_targeting_entities(
        raw_items: list[TargetingEntity],
    ) -> list[TargetingEntity]:
        """Remove duplicates from a list of targeting entities based on ID."""
        seen_ids = set()
        unique = []

        for item in raw_items:
            item_id = str(item.id) if item.id else None
            if not item_id or item_id in seen_ids:
                continue

            seen_ids.add(item_id)
            unique.append(item)

        return unique

    @staticmethod
    def _normalize_ad_account_id(ad_account_id: str) -> str:
        """Normalize Meta ad account ID by handling prefixes and whitespace."""
        clean_id = ad_account_id.strip().lower()
        if clean_id.startswith("act_"):
            return clean_id[4:]
        return clean_id
