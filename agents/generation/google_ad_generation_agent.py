import asyncio
import structlog

from services.generation.ad_text_service import AdTextService
from services.generation.age_service import AgeTargetingService
from services.generation.gender_service import GenderTargetingService

logger = structlog.get_logger(__name__)

_PLATFORM = "google"


class GoogleAdGenerationAgent:
    def __init__(self):
        self.ad_text_service = AdTextService()
        self.age_service = AgeTargetingService()
        self.gender_service = GenderTargetingService()

    async def generate(
        self,
        summary: str,
        keywords: list,
        requirements: str | None = None,
    ) -> dict:
        logger.info(
            "[GoogleAdGenerationAgent] Starting parallel generation",
            platform=_PLATFORM,
            keyword_count=len(keywords),
        )

        headlines, descriptions, age, gender = await asyncio.gather(
            self.ad_text_service.generate(
                summary=summary,
                platform=_PLATFORM,
                content_type="headlines",
                keywords=keywords,
                requirements=requirements,
            ),
            self.ad_text_service.generate(
                summary=summary,
                platform=_PLATFORM,
                content_type="descriptions",
                keywords=keywords,
                requirements=requirements,
            ),
            self.age_service.generate(summary=summary, platform=_PLATFORM),
            self.gender_service.generate(summary=summary, platform=_PLATFORM),
        )

        logger.info(
            "[GoogleAdGenerationAgent] Done",
            headlines=len(headlines),
            descriptions=len(descriptions),
            age_ranges=age.age_ranges,
            genders=gender.genders,
        )

        return {
            "headlines": headlines,
            "descriptions": descriptions,
            "age": {
                "age_ranges": age.age_ranges,
            },
            "gender": {
                "genders": gender.genders,
            },
        }


google_ad_generation_agent = GoogleAdGenerationAgent()
