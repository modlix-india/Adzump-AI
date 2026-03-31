import asyncio
import structlog

from services.generation.ad_text_service import AdTextService
from services.generation.age_service import AgeTargetingService
from services.generation.gender_service import GenderTargetingService

logger = structlog.get_logger(__name__)

_PLATFORM = "meta"


class MetaAdGenerationAgent:
    def __init__(self):
        self.ad_text_service = AdTextService()
        self.age_service = AgeTargetingService()
        self.gender_service = GenderTargetingService()

    async def generate(
        self,
        summary: str,
        requirements: str | None = None,
    ) -> dict:
        logger.info(
            "[MetaAdGenerationAgent] Starting parallel generation", platform=_PLATFORM
        )

        headlines, descriptions, primary_text, age, gender = await asyncio.gather(
            self.ad_text_service.generate(
                summary=summary,
                platform=_PLATFORM,
                content_type="headlines",
                requirements=requirements,
            ),
            self.ad_text_service.generate(
                summary=summary,
                platform=_PLATFORM,
                content_type="descriptions",
                requirements=requirements,
            ),
            self.ad_text_service.generate(
                summary=summary,
                platform=_PLATFORM,
                content_type="primary_text",
                requirements=requirements,
            ),
            self.age_service.generate(summary=summary, platform=_PLATFORM),
            self.gender_service.generate(summary=summary, platform=_PLATFORM),
        )

        logger.info(
            "[MetaAdGenerationAgent] Done",
            headlines=len(headlines),
            primary_text=len(primary_text),
            descriptions=len(descriptions),
            age_min=age.age_min,
            age_max=age.age_max,
            genders=gender.genders,
        )

        return {
            "headlines": headlines,
            "primary_text": primary_text,
            "descriptions": descriptions,
            "age": {
                "age_min": age.age_min,
                "age_max": age.age_max,
            },
            "gender": {
                "genders": gender.genders,
            },
        }


meta_ad_generation_agent = MetaAdGenerationAgent()
