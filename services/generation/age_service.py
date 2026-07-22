import json
import structlog
from core.models.shared import AgeTargeting
from services.generation.platform_config import get_platform_config
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = structlog.get_logger(__name__)

_AGE_PROMPT = "generation/age_targeting_prompt.txt"


class AgeTargetingService:
    async def generate(
        self,
        summary: str,
        platform: str,
    ) -> AgeTargeting:
        cfg = get_platform_config(platform)

        logger.info(
            "[AgeTargetingService] Starting",
            platform=platform,
            output_format=cfg.age_output_format,
        )

        template = load_prompt(_AGE_PROMPT)
        prompt = template.format(
            platform=platform,
            output_format=cfg.age_output_format,
            age_min_allowed=cfg.age_min_allowed,
            age_max_allowed=cfg.age_max_allowed,
            valid_age_ranges=json.dumps(cfg.valid_age_ranges),
            summary=summary,
        )

        response = await chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are an ad targeting specialist. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            model=cfg.llm_model,
        )

        raw = response.choices[0].message.content or ""

        if response.usage:
            logger.info(
                "[AgeTargetingService] Token usage",
                total_tokens=response.usage.total_tokens,
                platform=platform,
            )

        return self._parse_and_validate(raw, cfg, platform)

    def _parse_and_validate(self, raw: str, cfg, platform: str) -> AgeTargeting:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.error("[AgeTargetingService] Failed to parse JSON", raw=raw)
            return AgeTargeting()

        if cfg.age_output_format == "min_max":
            age_min = data.get("age_min")
            age_max = data.get("age_max")

            if isinstance(age_min, int):
                age_min = max(cfg.age_min_allowed, min(cfg.age_max_allowed, age_min))
            if isinstance(age_max, int):
                age_max = max(cfg.age_min_allowed, min(cfg.age_max_allowed, age_max))

            logger.info(
                "[AgeTargetingService] Meta result", age_min=age_min, age_max=age_max
            )
            return AgeTargeting(age_min=age_min, age_max=age_max, age_ranges=[])

        elif cfg.age_output_format == "ranges":
            raw_ranges = data.get("age_ranges", [])
            valid = [r for r in raw_ranges if r in cfg.valid_age_ranges]
            invalid = set(raw_ranges) - set(valid)
            if invalid:
                logger.warning(
                    "[AgeTargetingService] Filtered invalid age ranges",
                    invalid=sorted(invalid),
                    platform=platform,
                )
            logger.info("[AgeTargetingService] Google result", age_ranges=valid)
            return AgeTargeting(age_min=None, age_max=None, age_ranges=valid)

        logger.error(
            "[AgeTargetingService] Unknown age_output_format",
            format=cfg.age_output_format,
        )
        return AgeTargeting()
