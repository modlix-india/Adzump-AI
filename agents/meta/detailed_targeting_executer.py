import asyncio
import json
from types import MappingProxyType

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

# Open AI Models
SEED_MODEL = "gpt-4o-mini"
FILTER_MODEL = "gpt-4o"

# Prompt path for filtering
FILTER_PROMPT_PATH = "meta/detailed_targeting_analysis.txt"

# Meta API
META_FETCH_TIMEOUT = 15.0
META_MAX_ATTEMPTS = 2  # 1 attempt + 1 retry

# Meta API Batching and Limits
META_SUGGESTIONS_BATCH_SIZE = 10
META_SUGGESTIONS_MAX_IDS = 50
META_SUGGESTIONS_LIMIT = 45
META_VALIDATION_BATCH_SIZE = 50

# LLM
LLM_BATCH_SIZE = 30
LLM_MAX_ATTEMPTS = 3  # 1 attempt + 2 retries
LLM_TIMEOUT = 35

# Concurrency guards — shared across all requests
META_SEMAPHORE = asyncio.Semaphore(10)
LLM_SEMAPHORE = asyncio.Semaphore(5)

# Seed prompt file per category
CATEGORY_SEED_PROMPTS = MappingProxyType(
    {
        TargetingCategory.INTERESTS: "meta/interest_suggestions.txt",
        TargetingCategory.DEMOGRAPHICS: "meta/demographics_suggestions.txt",
        TargetingCategory.BEHAVIORS: "meta/behaviors_suggestions.txt",
    }
)

# Default maximum results if category is not in CATEGORY_LIMITS
DEFAULT_CATEGORY_LIMIT = 15

# Maximum results returned per category after LLM filtering
CATEGORY_LIMITS = MappingProxyType(
    {
        TargetingCategory.INTERESTS: 25,
        TargetingCategory.DEMOGRAPHICS: 15,
        TargetingCategory.BEHAVIORS: 20,
    }
)

# Valid limit_type values for act_{id}/targetingsearch — demographics sub-types only.
# "demographics" is NOT a valid value. Must use specific sub-types.
# Source: https://developers.facebook.com/docs/marketing-api/audiences/reference/detailed-targeting
DEMOGRAPHIC_LIMIT_TYPES = (
    "life_events",
    "family_statuses",
    "income",
    "industries",
    "work_positions",
    "work_employers",
    "education_majors",
    "education_statuses",
)

# Normalised type strings Meta returns per category across different endpoints
INTEREST_TYPE_LABELS = frozenset(["interests", "interest", "adinterest"])
BEHAVIOR_TYPE_LABELS = frozenset(["behaviors", "behavior"])


class MetaTargetingExecutor:
    """
    Stateless executor for the Meta Ads detailed targeting pipeline.

    This executor implements a "Meta-Grounded" discovery strategy, which maps business
    requirements to Meta's specific API taxonomies (Interests, Behaviors, and Demographics).

    Fetch strategy per category:
    - INTERESTS:    Two-phase discovery (Keyword Search + ID-based Suggestions).
    - BEHAVIORS:    Catalogue-first (Browse full taxonomy + Keyword supplement).
    - DEMOGRAPHICS: Taxonomy-first (Browse categories + Parallel sub-type keyword searches).
    """

    async def run_targeting_pipeline(
        self,
        ad_account_id: str,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[TargetingEntity]:
        """Run the full targeting pipeline for a single category."""
        # Validate category and bind context variables
        try:
            category = TargetingCategory(category)
        except (ValueError, TypeError):
            raise BusinessValidationException(f"Invalid targeting category: {category}")

        # Bind contextual information to the logger for this execution.
        structlog.contextvars.bind_contextvars(category=category.value)

        try:
            # Normalize ad account ID for API consistency
            account_id = self._normalize_ad_account_id(ad_account_id)

            # Phase 1: Identify "Seed" keywords that map to Meta's index.
            # For Behaviors, seeds are supplementary; we proceed even if none are generated.
            seeds = await self._generate_seed_suggestions(category, business_summary)
            if not seeds and category != TargetingCategory.BEHAVIORS:
                logger.warning("meta_detailed_targeting.seeds.missing")
                return []

            # Deduplicate and diversify seeds to maximize audience coverage
            diverse_seeds = self._diversify_seeds(seeds) if seeds else []
            if diverse_seeds:
                logger.info(
                    "meta_detailed_targeting.seeds.diversified",
                    original_count=len(seeds),
                    diverse_count=len(diverse_seeds),
                    seeds=diverse_seeds,
                )

            # Phase 2: Fetch raw targeting candidates from Meta.
            # Dispatches to category-specific strategies (ID expansion, catalogue browse, etc.)
            raw_candidates = await self._fetch_meta_targeting_candidates(
                account_id, category, diverse_seeds
            )
            if not raw_candidates:
                logger.warning("meta_detailed_targeting.candidates.missing")
                return []

            # Phase 3: Technical filtering and deduplication.
            # Normalizes type labels and ensures each ID appears only once in the pool.
            category_filtered = self._filter_targeting_by_category(
                raw_candidates, category
            )
            unique_candidates = self._deduplicate_targeting_entities(category_filtered)

            logger.info(
                "meta_detailed_targeting.candidates.ready",
                total_fetched=len(raw_candidates),
                after_filter=len(category_filtered),
                after_dedup=len(unique_candidates),
            )

            # Phase 4: Relevance curation via LLM.
            # We filter for relevance BEFORE validation to minimize expensive API calls.
            llm_results = await self._select_relevant_candidates_using_llm(
                category, business_summary, unique_candidates
            )

            # Phase 5: Deliverability validation.
            # Verifies each candidate ID is still active and valid in Meta's current index.
            validated_results = await self._validate_targeting_entities(
                account_id, llm_results
            )

            # Enforce category-specific limits to prevent audience over-segmentation
            limit = CATEGORY_LIMITS.get(category, DEFAULT_CATEGORY_LIMIT)
            final_results = validated_results[:limit]

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
            structlog.contextvars.unbind_contextvars("category")

    # Seed Generation
    async def _generate_seed_suggestions(
        self,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[str]:
        """
        Generate keyword seeds for the given category using a specialized prompt.
        These seeds act as the primary search queries for Meta's targeting search.
        """
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
                        "content": (
                            "You are a search strategist for Meta Ads audience discovery. "
                            "Generate specific search queries that surface the most relevant "
                            "audience segments when run against Meta's targeting API."
                        ),
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
            # Malformed JSON from LLM — treat as empty rather than failing the pipeline
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

    # Candidate Fetching — Category Router
    async def _fetch_meta_targeting_candidates(
        self,
        ad_account_id: str,
        category: TargetingCategory,
        seeds: list[str],
    ) -> list[TargetingEntity]:
        """Category-specific routing for candidate discovery."""
        if category == TargetingCategory.INTERESTS:
            return await self._fetch_interest_candidates(ad_account_id, seeds)
        elif category == TargetingCategory.BEHAVIORS:
            return await self._fetch_behavior_candidates(ad_account_id, seeds)
        elif category == TargetingCategory.DEMOGRAPHICS:
            return await self._fetch_demographic_candidates(ad_account_id, seeds)
        return []

    # Interests — Phase 1: keyword search, Phase 2: ID-based expansion
    async def _fetch_interest_candidates(
        self,
        ad_account_id: str,
        seeds: list[str],
    ) -> list[TargetingEntity]:
        """
        Fetch interest candidates using a two-phase "Seed & Expand" approach.

        Phase 1: Keyword search via /targetingsearch to find specific "Anchor" interests.
        Phase 2: ID-based expansion via /targetingsuggestions to find related segments.
        """
        # Phase 1: search each seed in parallel
        phase1_results = await asyncio.gather(
            *[
                self._fetch_with_retry(
                    ad_account_id=ad_account_id,
                    endpoint="targetingsearch",
                    params={"q": seed, "limit_type": "interests"},
                    log_context={"seed": seed},
                )
                for seed in seeds
            ],
            return_exceptions=True,
        )

        phase1_entities: list[TargetingEntity] = []
        for seed, result in zip(seeds, phase1_results):
            if isinstance(result, Exception):
                logger.warning(
                    "meta_detailed_targeting.interests.phase1.failed",
                    seed=seed,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            phase1_entities.extend(result)

        logger.info(
            "meta_detailed_targeting.interests.phase1.complete",
            candidate_count=len(phase1_entities),
        )

        if not phase1_entities:
            return []

        # Phase 2: batch Phase 1 IDs for the suggestions endpoint.
        # Cap total IDs to keep request sizes reasonable.
        valid_ids = [
            {"type": "interests", "id": int(entity.id)}
            for entity in phase1_entities
            if entity.id
        ]
        id_batches = [
            valid_ids[i : i + META_SUGGESTIONS_BATCH_SIZE]
            for i in range(
                0,
                min(len(valid_ids), META_SUGGESTIONS_MAX_IDS),
                META_SUGGESTIONS_BATCH_SIZE,
            )
        ]

        phase2_results = await asyncio.gather(
            *[
                self._fetch_with_retry(
                    ad_account_id=ad_account_id,
                    endpoint="targetingsuggestions",
                    params={
                        "targeting_list": json.dumps(batch),
                        "limit_type": "interests",
                        "limit": META_SUGGESTIONS_LIMIT,  # Meta-documented max
                    },
                    log_context={"batch_size": len(batch)},
                )
                for batch in id_batches
            ],
            return_exceptions=True,
        )

        phase2_entities: list[TargetingEntity] = []
        for result in phase2_results:
            if isinstance(result, Exception):
                logger.warning(
                    "meta_detailed_targeting.interests.phase2.failed",
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            phase2_entities.extend(result)

        logger.info(
            "meta_detailed_targeting.interests.phase2.complete",
            candidate_count=len(phase2_entities),
        )

        return phase1_entities + phase2_entities

    # Behaviors — Full catalogue browse + keyword supplement
    async def _fetch_behavior_candidates(
        self,
        ad_account_id: str,
        seeds: list[str],
    ) -> list[TargetingEntity]:
        """
        Fetch behavior candidates using a "Catalogue-First" approach.

        Meta behaviors are a fixed taxonomy. Keyword search often yields zero results.
        We browse the full catalogue and supplement with targeted keyword searches.
        """
        browse_task = self._fetch_with_retry(
            ad_account_id=ad_account_id,
            endpoint="targetingbrowse",
            params={"limit_type": "behaviors"},
            log_context={"type": "browse"},
        )

        search_tasks = [
            self._fetch_with_retry(
                ad_account_id=ad_account_id,
                endpoint="targetingsearch",
                params={"q": seed, "limit_type": "behaviors"},
                log_context={"seed": seed},
            )
            for seed in seeds
        ]

        all_results = await asyncio.gather(
            browse_task, *search_tasks, return_exceptions=True
        )

        aggregated: list[TargetingEntity] = []

        browse_result = all_results[0]
        if isinstance(browse_result, Exception):
            logger.warning(
                "meta_detailed_targeting.behaviors.browse.failed",
                error=str(browse_result),
                error_type=type(browse_result).__name__,
            )
        else:
            aggregated.extend(browse_result)
            logger.info(
                "meta_detailed_targeting.behaviors.browse.complete",
                candidate_count=len(browse_result),
            )

        for seed, result in zip(seeds, all_results[1:]):
            if isinstance(result, Exception):
                logger.warning(
                    "meta_detailed_targeting.behaviors.search.failed",
                    seed=seed,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            aggregated.extend(result)

        return aggregated

    # Demographics — Full taxonomy browse + parallel sub-type searches
    async def _fetch_demographic_candidates(
        self,
        ad_account_id: str,
        seeds: list[str],
    ) -> list[TargetingEntity]:
        """
        Fetch demographic candidates using a "Taxonomy-First" approach.

        Demographics are indexed across multiple specialized sub-types (Job Titles,
        Employers, etc.). We browse the base taxonomy and run parallel keyword
        searches across all valid sub-types to ensure maximum granularity.
        """
        # No limit_type on browse — "demographics" is not a valid value for browse.
        # Category filtering happens downstream in _filter_targeting_by_category.
        browse_task = self._fetch_with_retry(
            ad_account_id=ad_account_id,
            endpoint="targetingbrowse",
            params={},
            log_context={"type": "browse_all"},
        )

        # Cross-product of seeds x limit_types — all run in parallel
        search_tasks = [
            self._fetch_with_retry(
                ad_account_id=ad_account_id,
                endpoint="targetingsearch",
                params={"q": seed, "limit_type": limit_type},
                log_context={"seed": seed, "limit_type": limit_type},
            )
            for seed in seeds
            for limit_type in DEMOGRAPHIC_LIMIT_TYPES
        ]

        all_results = await asyncio.gather(
            browse_task, *search_tasks, return_exceptions=True
        )

        aggregated: list[TargetingEntity] = []

        browse_result = all_results[0]
        if isinstance(browse_result, Exception):
            logger.warning(
                "meta_detailed_targeting.demographics.browse.failed",
                error=str(browse_result),
                error_type=type(browse_result).__name__,
            )
        else:
            aggregated.extend(browse_result)
            logger.info(
                "meta_detailed_targeting.demographics.browse.complete",
                candidate_count=len(browse_result),
            )

        failed_searches = 0
        for result in all_results[1:]:
            if isinstance(result, Exception):
                failed_searches += 1
                continue
            aggregated.extend(result)

        if failed_searches:
            logger.warning(
                "meta_detailed_targeting.demographics.search.partial_failure",
                failed_count=failed_searches,
                total_searches=len(search_tasks),
            )

        return aggregated

    # Targeting Validation — Confirm IDs are active before returning
    async def _validate_targeting_entities(
        self,
        ad_account_id: str,
        entities: list[TargetingEntity],
    ) -> list[TargetingEntity]:
        """
        Confirm IDs are deliverable via Meta's /targetingvalidation endpoint.
        Filters out segments that Meta has deprecated or restricted for the account.
        """
        if not entities:
            return []

        # targetingvalidation accepts up to 50 IDs per request
        batches = [
            entities[i : i + META_VALIDATION_BATCH_SIZE]
            for i in range(0, len(entities), META_VALIDATION_BATCH_SIZE)
        ]

        async def validate_batch(
            batch: list[TargetingEntity],
        ) -> list[TargetingEntity]:
            try:
                targeting_list = [
                    {"type": self._resolve_validation_type(e), "id": str(e.id)}
                    for e in batch
                    if e.id
                ]

                result = await self._execute_meta_request(
                    endpoint=f"/act_{ad_account_id}/targetingvalidation",
                    params={"targeting_list": json.dumps(targeting_list)},
                )

                # Retain only IDs Meta reports as NORMAL
                active_ids = {
                    str(item.id)
                    for item in result
                    if getattr(item, "valid", False) is True
                }
                return [e for e in batch if str(e.id) in active_ids]

            except Exception as error:
                # Validation failure must not drop valid data — return full batch
                logger.warning(
                    "meta_detailed_targeting.validation.batch_failed",
                    error=str(error),
                )
                return batch

        results = await asyncio.gather(*[validate_batch(batch) for batch in batches])
        validated = [item for sublist in results for item in sublist]

        logger.info(
            "meta_detailed_targeting.validation.complete",
            before=len(entities),
            after=len(validated),
        )

        return validated

    # Base Meta API Call — With Retry
    async def _fetch_with_retry(
        self,
        ad_account_id: str,
        endpoint: str,
        params: dict,
        log_context: dict,
    ) -> list[TargetingEntity]:
        """Call act_{id}/{endpoint} with exponential backoff retry.

        Example: /act_508128451820487/targetingsearch
        """
        full_endpoint = f"/act_{ad_account_id}/{endpoint}"

        for attempt in range(META_MAX_ATTEMPTS):
            try:
                async with META_SEMAPHORE:
                    return await asyncio.wait_for(
                        self._execute_meta_request(full_endpoint, params),
                        timeout=META_FETCH_TIMEOUT,
                    )
            except Exception as error:
                if attempt < META_MAX_ATTEMPTS - 1:
                    logger.warning(
                        "meta_detailed_targeting.api.retry",
                        endpoint=endpoint,
                        attempt=attempt + 1,
                        error=str(error),
                        **log_context,
                    )
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        return []  # Unreachable — raise above always fires on final attempt(don't remove)

    async def _execute_meta_request(
        self,
        endpoint: str,
        params: dict,
    ) -> list[TargetingEntity]:
        """Execute a Meta API GET request and return parsed entities."""
        response = await meta_client.get(
            endpoint,
            client_code=auth_context.client_code,
            params=params,
        )

        if "error" in response:
            error_msg = response["error"].get("message") or str(response["error"])
            error_msg = error_msg[
                :500
            ]  # Prevent log bloat from oversized Meta error objects
            logger.error(
                "meta_detailed_targeting.api.error_response",
                error=error_msg,
                endpoint=endpoint,
            )
            raise MetaAPIException(f"Meta API error: {error_msg}")

        return [
            TargetingEntity.model_validate(item) for item in response.get("data", [])
        ]

    # Category Filtering
    def _filter_targeting_by_category(
        self,
        raw_items: list[TargetingEntity],
        category: TargetingCategory,
    ) -> list[TargetingEntity]:
        """Filter raw Meta results to the requested category type.

        Meta returns inconsistent type strings across endpoints so membership
        is checked against known label sets rather than exact string matching.
        """
        before_count = len(raw_items)
        if category == TargetingCategory.INTERESTS:
            filtered = [
                item
                for item in raw_items
                if str(item.type).lower() in INTEREST_TYPE_LABELS
            ]
        elif category == TargetingCategory.BEHAVIORS:
            filtered = [
                item
                for item in raw_items
                if str(item.type).lower() in BEHAVIOR_TYPE_LABELS
            ]
        elif category == TargetingCategory.DEMOGRAPHICS:
            # Demographics is equal to anything that is not an interest or behavior
            excluded = INTEREST_TYPE_LABELS | BEHAVIOR_TYPE_LABELS
            filtered = [
                item for item in raw_items if str(item.type).lower() not in excluded
            ]
        else:
            filtered = []

        logger.info(
            "meta_detailed_targeting.filter.complete",
            before=before_count,
            after=len(filtered),
        )

        return filtered

    # LLM Filtering
    async def _select_relevant_candidates_using_llm(
        self,
        category: TargetingCategory,
        business_summary: str,
        candidates: list[TargetingEntity],
    ) -> list[TargetingEntity]:
        """Filter candidates for business relevance using batched LLM calls."""
        if not candidates:
            return []

        batches = [
            candidates[idx : idx + LLM_BATCH_SIZE]
            for idx in range(0, len(candidates), LLM_BATCH_SIZE)
        ]

        tasks = [
            self._process_llm_filter_batch(
                batch, batch_index, category, business_summary
            )
            for batch_index, batch in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        selected_ids: set[str] = set()
        for result in results:
            if isinstance(result, list):
                selected_ids.update(str(res_id) for res_id in result)
            elif isinstance(result, Exception):
                logger.error("meta_detailed_targeting.batch.failed", error=str(result))

        relevant = [candidate for candidate in candidates if str(candidate.id) in selected_ids]

        # Sort by audience size so the largest relevant audiences rank first
        return sorted(
            relevant,
            key=lambda candidate: getattr(candidate, "audience_size_upper_bound", 0) or 0,
            reverse=True,
        )

    async def _process_llm_filter_batch(
        self,
        batch: list[TargetingEntity],
        batch_index: int,
        category: TargetingCategory,
        business_summary: str,
    ) -> list[str]:
        """Run LLM relevance filtering on a single batch with retry and backoff."""
        valid_ids = {str(item.id) for item in batch if item.id}
        prompt = format_prompt(
            FILTER_PROMPT_PATH,
            summary=business_summary,
            category=category.value,
            candidates=json.dumps(
                [
                    {"id": str(item.id), "name": item.name or "", "type": item.type or ""}
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
                                    "content": (
                                        "You are a ruthless Meta Ads relevance filter. "
                                        "Your default is to reject. Only keep candidates "
                                        "with a clear, direct, defensible connection to "
                                        "this specific business and buyer. Uncertain = reject."
                                    ),
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
                        str(sid) for sid in parsed.selected_ids if str(sid) in valid_ids
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

            if attempt < LLM_MAX_ATTEMPTS - 1:
                await asyncio.sleep(2**attempt)

        return []

    # Static Utilities — Defined in order of execution in the pipeline
    @staticmethod
    def _normalize_ad_account_id(ad_account_id: str) -> str:
        """Strip the act_ prefix from a Meta ad account ID if present.

        act_508128451820487 -> 508128451820487
        """
        clean_id = ad_account_id.strip().lower()
        if clean_id.startswith("act_"):
            return clean_id[4:]
        return clean_id

    @staticmethod
    def _diversify_seeds(seeds: list[str]) -> list[str]:
        """Remove seeds whose word overlap with any already-selected seed exceeds 60%."""
        # Pre-process seeds into sets of words to avoid redundant computation in the comparison loop
        processed_seeds: list[tuple[str, set[str]]] = []
        for seed in seeds:
            words = set(seed.lower().split())
            if not words:
                continue

            is_redundant = any(
                len(words & selected_words)
                / max(len(words), len(selected_words))
                > 0.6
                for _, selected_words in processed_seeds
            )

            if not is_redundant:
                processed_seeds.append((seed, words))

        return [seed for seed, _ in processed_seeds]

    @staticmethod
    def _deduplicate_targeting_entities(
        raw_items: list[TargetingEntity],
    ) -> list[TargetingEntity]:
        """Remove duplicate entities by Meta ID, preserving first occurrence."""
        seen_ids: set[str] = set()
        unique: list[TargetingEntity] = []

        for item in raw_items:
            item_id = str(item.id) if item.id else None
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            unique.append(item)

        return unique

    @staticmethod
    def _resolve_validation_type(entity: TargetingEntity) -> str:
        """Resolve the canonical type string required by targetingvalidation."""
        raw = str(entity.type).lower()
        if raw in INTEREST_TYPE_LABELS:
            return "interests"
        if raw in BEHAVIOR_TYPE_LABELS:
            return "behaviors"
        # Life events, income, work_positions etc. pass through as-is
        return raw
