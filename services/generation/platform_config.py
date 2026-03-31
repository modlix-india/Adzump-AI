from typing import Literal
from pydantic import BaseModel


PlatformType = Literal["google", "meta"]


class ContentTypeConfig(BaseModel):
    prompt: str  # path relative to prompts/ dir
    min_count: int
    min_chars: int
    max_chars: int
    similarity: float
    requires_keywords: bool = False


class PlatformConfig(BaseModel):
    # LLM
    llm_model: str
    max_retries: int
    temp_start: float

    # All text content types for this platform
    # Keys: "headlines", "descriptions", "primary_text" (Meta only), etc.
    content_types: dict[str, ContentTypeConfig]

    # Age targeting
    age_output_format: Literal["min_max", "ranges"]
    age_min_allowed: int
    age_max_allowed: int
    valid_age_ranges: list[str]

    # Gender targeting
    gender_output_format: Literal["list", "types"]
    valid_genders: list[str]

    def get_content_type(self, content_type: str) -> ContentTypeConfig:
        if content_type not in self.content_types:
            raise ValueError(
                f"Content type '{content_type}' not configured for this platform. "
                f"Available: {list(self.content_types.keys())}"
            )
        return self.content_types[content_type]


PLATFORM_CONFIG: dict[str, PlatformConfig] = {
    "google": PlatformConfig(
        llm_model="gpt-4o-mini",
        max_retries=3,
        temp_start=0.7,
        content_types={
            "headlines": ContentTypeConfig(
                prompt="generation/google_headlines_prompt.txt",
                min_count=15,
                min_chars=20,
                max_chars=30,
                similarity=0.8,
                requires_keywords=True,
            ),
            "descriptions": ContentTypeConfig(
                prompt="generation/google_descriptions_prompt.txt",
                min_count=4,
                min_chars=75,
                max_chars=90,
                similarity=0.7,
                requires_keywords=True,
            ),
        },
        age_output_format="ranges",
        age_min_allowed=18,
        age_max_allowed=65,
        valid_age_ranges=[
            "AGE_RANGE_18_24",
            "AGE_RANGE_25_34",
            "AGE_RANGE_35_44",
            "AGE_RANGE_45_54",
            "AGE_RANGE_55_64",
            "AGE_RANGE_65_UP",
        ],
        gender_output_format="types",
        valid_genders=["MALE", "FEMALE", "UNDETERMINED"],
    ),
    "meta": PlatformConfig(
        llm_model="gpt-4o-mini",
        max_retries=3,
        temp_start=0.7,
        content_types={
            "headlines": ContentTypeConfig(
                prompt="generation/meta_headlines_prompt.txt",
                min_count=5,
                min_chars=20,
                max_chars=40,
                similarity=0.85,
                requires_keywords=False,
            ),
            "descriptions": ContentTypeConfig(
                prompt="generation/meta_descriptions_prompt.txt",
                min_count=5,
                min_chars=10,
                max_chars=35,
                similarity=0.80,
                requires_keywords=False,
            ),
            "primary_text": ContentTypeConfig(
                prompt="generation/meta_primary_text_prompt.txt",
                min_count=5,
                min_chars=60,
                max_chars=125,
                similarity=0.80,
                requires_keywords=False,
            ),
        },
        age_output_format="min_max",
        age_min_allowed=18,
        age_max_allowed=65,
        valid_age_ranges=[],
        gender_output_format="list",
        valid_genders=["MALE", "FEMALE"],
    ),
}


def get_platform_config(platform: str) -> PlatformConfig:
    if platform not in PLATFORM_CONFIG:
        raise ValueError(
            f"Unsupported platform '{platform}'. "
            f"Supported: {list(PLATFORM_CONFIG.keys())}"
        )
    return PLATFORM_CONFIG[platform]
