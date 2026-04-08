import json
import structlog

from core.models.shared import GenderTargeting
from services.generation.platform_config import get_platform_config
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = structlog.get_logger(__name__)

_GENDER_PROMPT = "generation/gender_targeting_prompt.txt"


class GenderTargetingService:
    async def generate(
        self,
        summary: str,
        platform: str,
    ) -> GenderTargeting:
        cfg = get_platform_config(platform)

        logger.info(
            "[GenderTargetingService] Starting",
            platform=platform,
            valid_genders=cfg.valid_genders,
        )

        template = load_prompt(_GENDER_PROMPT)
        prompt = template.format(
            platform=platform,
            valid_genders=json.dumps(cfg.valid_genders),
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
                "[GenderTargetingService] Token usage",
                total_tokens=response.usage.total_tokens,
                platform=platform,
            )

        return self._parse_and_validate(raw, cfg, platform)

    def _parse_and_validate(self, raw: str, cfg, platform: str) -> GenderTargeting:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.error("[GenderTargetingService] Failed to parse JSON", raw=raw)
            return GenderTargeting(genders=cfg.valid_genders)

        raw_genders = data.get("genders", [])
        normalised = [g.upper() for g in raw_genders if isinstance(g, str)]
        valid = [g for g in normalised if g in cfg.valid_genders]
        invalid = set(normalised) - set(valid)

        if invalid:
            logger.warning(
                "[GenderTargetingService] Filtered invalid genders",
                invalid=sorted(invalid),
                platform=platform,
            )

        if not valid:
            logger.warning(
                "[GenderTargetingService] No valid genders returned — using all allowed",
                platform=platform,
                fallback=cfg.valid_genders,
            )
            valid = cfg.valid_genders

        logger.info("[GenderTargetingService] Result", genders=valid, platform=platform)
        return GenderTargeting(genders=valid)
