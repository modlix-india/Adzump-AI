import json
import structlog
from openai import RateLimitError, APIError
import asyncio

from services.generation.platform_config import (
    get_platform_config,
    PlatformConfig,
    ContentTypeConfig,
)
from services.generation.ad_text_utils import (
    deduplicate_items,
    filter_by_length,
    rescue_pool_fallback,
)
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = structlog.get_logger(__name__)


class AdTextService:
    async def generate(
        self,
        summary: str,
        platform: str,
        content_type: str,
        keywords: list | None = None,
    ) -> list[str]:
        cfg = get_platform_config(platform)
        type_cfg = cfg.get_content_type(content_type)

        if type_cfg.requires_keywords and not keywords:
            raise ValueError(
                f"Platform '{platform}' requires keywords for '{content_type}' generation."
            )

        logger.info(
            "[AdTextService] Starting generation",
            platform=platform,
            content_type=content_type,
            min_count=type_cfg.min_count,
        )

        all_raw: list[str] = []
        result: list[str] = []

        for attempt in range(cfg.max_retries):
            temperature = cfg.temp_start + (attempt * 0.1)

            logger.info(
                "[AdTextService] Attempt",
                content_type=content_type,
                attempt=attempt + 1,
                max_retries=cfg.max_retries,
                temperature=temperature,
            )

            try:
                raw_items = await self._call_llm(
                    summary, keywords, cfg, type_cfg, temperature
                )
                all_raw.extend(raw_items)

                # Quality check AFTER filter + dedup on the cumulative pool
                filtered = filter_by_length(
                    all_raw, type_cfg.min_chars, type_cfg.max_chars
                )
                deduped = deduplicate_items(filtered, type_cfg.similarity)

                logger.info(
                    "[AdTextService] Attempt result",
                    content_type=content_type,
                    attempt=attempt + 1,
                    raw_this_call=len(raw_items),
                    cumulative_raw=len(all_raw),
                    after_filter=len(filtered),
                    after_dedup=len(deduped),
                    need=type_cfg.min_count,
                )

                if len(deduped) >= type_cfg.min_count:
                    result = sorted(deduped, key=len, reverse=True)[
                        : type_cfg.min_count
                    ]
                    logger.info(
                        "[AdTextService] Quality met",
                        content_type=content_type,
                        attempt=attempt + 1,
                        final_count=len(result),
                    )
                    break

                logger.warning(
                    "[AdTextService] Quality failure — retrying",
                    content_type=content_type,
                    got=len(deduped),
                    need=type_cfg.min_count,
                    attempt=attempt + 1,
                )

            except (RateLimitError, APIError) as api_err:
                wait = 2**attempt
                logger.warning(
                    "[AdTextService] API error — backing off",
                    content_type=content_type,
                    error=str(api_err),
                    wait_seconds=wait,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)

        if not result:
            result = rescue_pool_fallback(
                all_items=all_raw,
                min_chars=type_cfg.min_chars,
                max_chars=type_cfg.max_chars,
                similarity_threshold=type_cfg.similarity,
                min_count=type_cfg.min_count,
                label=content_type,
            )

        logger.info(
            "[AdTextService] Done",
            platform=platform,
            content_type=content_type,
            final_count=len(result),
        )
        return result

    async def _call_llm(
        self,
        summary: str,
        keywords: list | None,
        cfg: PlatformConfig,
        type_cfg: ContentTypeConfig,
        temperature: float,
    ) -> list[str]:
        template = load_prompt(type_cfg.prompt)
        prompt = template.format(
            summary=summary,
            keywords=json.dumps(keywords or [], indent=2),
        )
        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=cfg.llm_model,
            temperature=temperature,
        )
        raw = response.choices[0].message.content or ""

        if response.usage:
            logger.info(
                "[AdTextService] Token usage",
                content_type=type_cfg.prompt,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                temperature=temperature,
            )

        import json as _json

        try:
            parsed = _json.loads(raw.strip())
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            if isinstance(parsed, dict):
                for key in ("headlines", "descriptions", "primary_text", "items"):
                    if key in parsed:
                        return [str(item) for item in parsed[key]]
        except Exception:
            pass
        return []
