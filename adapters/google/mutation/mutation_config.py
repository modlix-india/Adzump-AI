from dataclasses import dataclass, field
from typing import FrozenSet
from core.models.optimization import (
    HEADLINE_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    SITELINK_TEXT_MAX_LENGTH,
    SITELINK_DESCRIPTION_MAX_LENGTH,
    KEYWORD_MAX_LENGTH,
    URL_MAX_LENGTH,
    AGE_RANGE_VALUES,
    GENDER_RANGE_VALUES,
    MATCH_TYPE_VALUES,
)

# Source for System limits: https://developers.google.com/google-ads/api/docs/best-practices/system-limits


@dataclass(frozen=True)
class _HeadlineConfig:
    """Constraints for RSA headlines."""

    # Source1:https://support.google.com/google-ads/answer/7684791
    # Source2: https://support.google.com/google-ads/answer/1704389
    MAX_LENGTH: int = HEADLINE_MAX_LENGTH
    MIN_COUNT: int = 3
    MAX_COUNT: int = 15


@dataclass(frozen=True)
class _DescriptionConfig:
    """Constraints for RSA descriptions."""

    # Source1:https://support.google.com/google-ads/answer/7684791
    # Source2: https://support.google.com/google-ads/answer/1704389
    MAX_LENGTH: int = DESCRIPTION_MAX_LENGTH
    MIN_COUNT: int = 2
    MAX_COUNT: int = 4


@dataclass(frozen=True)
class _SitelinkConfig:
    """Constraints for Sitelink assets."""

    # Source1: https://developers.google.com/google-ads/api/reference/rpc/v23/SitelinkAsset
    # Source2: https://support.google.com/google-ads/answer/2375416
    LINK_TEXT_MAX_LENGTH: int = SITELINK_TEXT_MAX_LENGTH
    DESCRIPTION_MAX_LENGTH: int = SITELINK_DESCRIPTION_MAX_LENGTH
    MIN_COUNT: int = 2
    MAX_DISPLAY_DESKTOP: int = 6
    MAX_DISPLAY_MOBILE: int = 8


@dataclass(frozen=True)
class _ProximityConfig:
    """Constraints for Proximity (radius) targeting."""

    # Source: https://developers.google.com/google-ads/api/reference/rpc/v23/ProximityInfo

    MILES_TO_KM: float = 1.60934
    MIN_RADIUS_KM: int = 1
    MAX_RADIUS_KM: int = 800  # 500 miles
    VALID_UNITS: FrozenSet[str] = field(
        default_factory=lambda: frozenset({"MILES", "KILOMETERS"})
    )


@dataclass(frozen=True)
class _AgeConfig:
    """Valid age range enum values from Google Ads API v21."""

    # Source: https://developers.google.com/google-ads/api/reference/rpc/v21/AgeRangeTypeEnum.AgeRangeType
    VALID_RANGES: FrozenSet[str] = field(
        default_factory=lambda: frozenset(AGE_RANGE_VALUES)
    )


@dataclass(frozen=True)
class _GenderConfig:
    """Valid gender type enum values from Google Ads API v21."""

    # Source: https://developers.google.com/google-ads/api/reference/rpc/v21/GenderTypeEnum.GenderType
    VALID_TYPES: FrozenSet[str] = field(
        default_factory=lambda: frozenset(GENDER_RANGE_VALUES)
    )


@dataclass(frozen=True)
class _KeywordConfig:
    """Constraints for Keyword criteria."""

    # Source: https://developers.google.com/google-ads/api/reference/rpc/v23/KeywordInfo
    MAX_LENGTH: int = KEYWORD_MAX_LENGTH
    VALID_MATCH_TYPES: FrozenSet[str] = field(
        default_factory=lambda: frozenset(MATCH_TYPE_VALUES)
    )


@dataclass(frozen=True)
class GoogleAdsMutationConfig:
    """Centralized, immutable configuration for Google Ads mutations."""

    HEADLINES: _HeadlineConfig = _HeadlineConfig()
    DESCRIPTIONS: _DescriptionConfig = _DescriptionConfig()
    SITELINKS: _SitelinkConfig = _SitelinkConfig()
    PROXIMITY: _ProximityConfig = _ProximityConfig()
    KEYWORDS: _KeywordConfig = _KeywordConfig()
    AGE: _AgeConfig = field(default_factory=_AgeConfig)
    GENDER: _GenderConfig = field(default_factory=_GenderConfig)

    URL_MAX_LENGTH: int = URL_MAX_LENGTH
    ASSET_FIELD_TYPE_SITELINK: str = "SITELINK"


# Global immutable configuration instance
CONFIG = GoogleAdsMutationConfig()
