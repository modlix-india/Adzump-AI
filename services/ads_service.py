import json
from difflib import SequenceMatcher
from services.json_utils import safe_json_parse
from services.openai_client import chat_completion
from utils import prompt_loader
from structlog import get_logger

logger = get_logger(__name__)


class AdAssetsGenerator:
    def __init__(
        self,
        max_attempts: int = 3,
        min_headlines: int = 15,
        min_descriptions: int = 4,
    ):
        self.max_attempts = max_attempts
        self.min_headlines = min_headlines
        self.min_descriptions = min_descriptions

        # Base constraints (common across all attempts)
        self.base_config = {"h_min": 20, "h_max": 30, "d_min": 75, "d_max": 90}

        # Fallback configuration (soft minimums)
        self.fallback_config = {
            "sim_h": 0.95,
            "sim_d": 0.85,
            "h_min": 15,
            "h_max": 30,
            "d_min": 60,
            "d_max": 90,
        }

    async def generate(self, summary, positive_keywords) -> dict:
        all_raw_headlines = []
        all_raw_descriptions = []
        last_audience = {}

        for attempt_num in range(self.max_attempts):
            config = self._get_attempt_config(attempt_num)

            logger.info(
                f"[AdAssets] Starting attempt {attempt_num + 1}/{self.max_attempts}",
                temperature=config["temp"],
                similarity_headlines=config["sim_h"],
                similarity_descriptions=config["sim_d"],
            )

            try:
                result = await self._generate_single_attempt(
                    summary, positive_keywords, config
                )

                # Accumulate raw items for potential rescue pool
                all_raw_headlines.extend(result["raw_headlines"])
                all_raw_descriptions.extend(result["raw_descriptions"])

                filtered = result["filtered"]
                last_audience = filtered.get("audience", {})

                h_count = len(filtered["headlines"])
                d_count = len(filtered["descriptions"])

                logger.info(
                    f"[AdAssets] Attempt {attempt_num + 1} filtered results",
                    headlines=h_count,
                    descriptions=d_count,
                    success=(
                        h_count >= self.min_headlines
                        and d_count >= self.min_descriptions
                    ),
                )

                # Check if requirements met
                if h_count >= self.min_headlines and d_count >= self.min_descriptions:
                    logger.info(
                        f"[AdAssets] ✓ Success on attempt {attempt_num + 1}",
                        headlines=h_count,
                        descriptions=d_count,
                    )
                    return filtered

                logger.warning(
                    f"[AdAssets] Attempt {attempt_num + 1} insufficient - will retry",
                    headlines_shortage=max(0, self.min_headlines - h_count),
                    descriptions_shortage=max(0, self.min_descriptions - d_count),
                )

            except Exception as e:
                logger.error(
                    f"[AdAssets] Attempt {attempt_num + 1} exception",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                if attempt_num == self.max_attempts - 1:
                    logger.critical("[AdAssets] All attempts failed with exceptions")
                    raise

        # All attempts exhausted - fallback to rescue pool
        logger.warning(
            "[AdAssets] All attempts insufficient - activating rescue pool",
            total_attempts=self.max_attempts,
        )

        result = self._rescue_pool_fallback(all_raw_headlines, all_raw_descriptions)
        result["audience"] = last_audience

        return result

    def _get_attempt_config(self, attempt_num: int) -> dict:
        return {
            **self.base_config,
            "temp": 0.7 + (attempt_num * 0.1),
            "sim_h": 0.8 + (attempt_num * 0.05),
            "sim_d": 0.7 + (attempt_num * 0.05),
        }

    def _deduplicate_items(
        self, items: list[str], similarity_threshold: float = 0.7
    ) -> list[str]:
        if not items:
            return []

        # First pass: remove exact duplicates (case-insensitive)
        seen_lower = set()
        unique_items = []
        for item in items:
            item_lower = item.lower().strip()
            if item_lower not in seen_lower:
                seen_lower.add(item_lower)
                unique_items.append(item)

        # Second pass: remove semantically similar items
        final_items = []
        for item in unique_items:
            is_similar = False
            for existing in final_items:
                ratio = SequenceMatcher(None, item.lower(), existing.lower()).ratio()
                if ratio >= similarity_threshold:
                    is_similar = True
                    logger.debug(
                        "[AdAssets] Removed similar item",
                        removed=item,
                        similar_to=existing,
                        similarity=round(ratio, 2),
                    )
                    break
            if not is_similar:
                final_items.append(item)

        return final_items

    def _filter_headlines(self, headlines: list[str], config: dict) -> list[str]:
        if not headlines:
            return []

        deduped = self._deduplicate_items(headlines, config["sim_h"])
        logger.info(
            "[AdAssets] Headlines after deduplication",
            count=len(deduped),
            threshold=config["sim_h"],
        )

        filtered = [h for h in deduped if config["h_min"] <= len(h) <= config["h_max"]]
        logger.info(
            "[AdAssets] Headlines after length filter",
            count=len(filtered),
            min_len=config["h_min"],
            max_len=config["h_max"],
        )

        sorted_headlines = sorted(filtered, key=len, reverse=True)
        return sorted_headlines[: self.min_headlines]

    def _filter_descriptions(self, descriptions: list[str], config: dict) -> list[str]:
        if not descriptions:
            return []

        deduped = self._deduplicate_items(descriptions, config["sim_d"])
        logger.info(
            "[AdAssets] Descriptions after deduplication",
            count=len(deduped),
            threshold=config["sim_d"],
        )

        filtered = [d for d in deduped if config["d_min"] <= len(d) <= config["d_max"]]
        logger.info(
            "[AdAssets] Descriptions after length filter",
            count=len(filtered),
            min_len=config["d_min"],
            max_len=config["d_max"],
        )

        sorted_descriptions = sorted(filtered, key=len, reverse=True)
        return sorted_descriptions[: self.min_descriptions]

    async def _generate_single_attempt(
        self, summary, positive_keywords, config: dict
    ) -> dict:
        try:
            prompt = prompt_loader.format_prompt(
                "ad_assets_prompt.txt",
                summary_json=json.dumps(summary, indent=2),
                positive_keywords_json=json.dumps(positive_keywords, indent=2),
            )

            response = await chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                temperature=config["temp"],
            )

            if response.usage:
                logger.info(
                    "[AdAssets] Token usage",
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    temperature=config["temp"],
                )

            raw_output = response.choices[0].message.content.strip()
            parsed = safe_json_parse(raw_output)

            if not parsed:
                return {
                    "filtered": {"headlines": [], "descriptions": [], "audience": {}},
                    "raw_headlines": [],
                    "raw_descriptions": [],
                }

            raw_headlines = parsed.get("headlines", [])
            raw_descriptions = parsed.get("descriptions", [])

            logger.info(
                "[AdAssets] Raw items from LLM",
                headlines_count=len(raw_headlines),
                descriptions_count=len(raw_descriptions),
            )

            # Apply filtering
            filtered_headlines = self._filter_headlines(raw_headlines, config)
            filtered_descriptions = self._filter_descriptions(raw_descriptions, config)

            return {
                "filtered": {
                    "headlines": filtered_headlines,
                    "descriptions": filtered_descriptions,
                    "audience": parsed.get("audience", {}),
                },
                "raw_headlines": raw_headlines,
                "raw_descriptions": raw_descriptions,
            }

        except Exception as e:
            logger.error("[AdAssets] Generation attempt failed", error=str(e))
            return {
                "filtered": {"headlines": [], "descriptions": [], "audience": {}},
                "raw_headlines": [],
                "raw_descriptions": [],
            }

    def _rescue_pool_fallback(
        self, all_headlines: list[str], all_descriptions: list[str]
    ) -> dict:
        config = self.fallback_config

        logger.warning(
            "[AdAssets] Executing rescue pool fallback",
            total_headlines_pool=len(all_headlines),
            total_descriptions_pool=len(all_descriptions),
            config=config,
        )

        rescued_headlines = self._filter_headlines(all_headlines, config)
        rescued_descriptions = self._filter_descriptions(all_descriptions, config)

        h_count = len(rescued_headlines)
        d_count = len(rescued_descriptions)

        logger.info(
            "[AdAssets] Rescue pool results",
            headlines=h_count,
            descriptions=d_count,
            headlines_needed=max(0, self.min_headlines - h_count),
            descriptions_needed=max(0, self.min_descriptions - d_count),
        )

        if h_count < self.min_headlines or d_count < self.min_descriptions:
            logger.critical(
                "[AdAssets] CRITICAL: Rescue pool unable to meet minimum requirements",
                headlines_got=h_count,
                headlines_needed=self.min_headlines,
                descriptions_got=d_count,
                descriptions_needed=self.min_descriptions,
            )

        return {
            "headlines": rescued_headlines,
            "descriptions": rescued_descriptions,
            "audience": {},
        }
