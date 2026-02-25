"""Field Validators - Pure validation functions for ad plan fields."""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

from word2number import w2n  # type: ignore[import-untyped]

from utils.helpers import validate_domain_exists

ValidatorResult = Tuple[Optional[str | int], Optional[str]]


def normalize_url(url: str) -> Optional[str]:
    """Normalize URL, returns None if invalid."""
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        if parsed.scheme not in ["http", "https"]:
            return None

        hostname = parsed.hostname
        if not hostname:
            return None

        if not re.match(
            r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
            hostname,
            re.IGNORECASE,
        ):
            return None

        if "." not in hostname:
            return None

        return url
    except Exception:
        return None


async def validate_website(url: str) -> ValidatorResult:
    """Validate and normalize website URL. Returns (normalized_value, error)."""
    normalized = normalize_url(url)
    if not normalized:
        return None, "Invalid URL format"

    is_valid, error = await validate_domain_exists(normalized)
    if not is_valid:
        return None, error

    return normalized, None


def parse_budget_string(value: str) -> str:
    """Parse budget string to numeric string. Raises ValueError on failure."""
    original_v = str(value).strip()
    v = original_v.lower()

    v = re.sub(
        r"\b(dollars?|rupees?|inr|usd|rs\.?|approximately|around|about|bucks)\b",
        "",
        v,
        flags=re.IGNORECASE,
    )
    v = re.sub(r"[$,₹€£¥]", "", v)

    # Try word-based numbers
    try:
        number_words = [
            "hundred",
            "thousand",
            "million",
            "billion",
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
        ]

        if any(word in v for word in number_words):
            word_part = re.sub(r"\d+.*", "", v).strip()
            if word_part:
                try:
                    return str(w2n.word_to_num(word_part))
                except ValueError:
                    pass
    except Exception:
        pass

    # lakh/crore
    lakh_crore_pattern = r"(\d+(?:\.\d+)?)\s*(lakh?s?|crore?s?)\b"
    lakh_crore_match = re.search(lakh_crore_pattern, v)
    if lakh_crore_match:
        number = float(lakh_crore_match.group(1))
        unit = lakh_crore_match.group(2).lower()
        if "lakh" in unit:
            return str(int(number * 100000))
        elif "crore" in unit:
            return str(int(number * 10000000))

    # k/m multipliers
    multiplier_pattern = r"(\d+(?:\.\d+)?)\s*([km])\b"
    multiplier_match = re.search(multiplier_pattern, v, flags=re.IGNORECASE)
    if multiplier_match:
        number = float(multiplier_match.group(1))
        multiplier = multiplier_match.group(2).lower()
        if multiplier == "k":
            return str(int(number * 1000))
        elif multiplier == "m":
            return str(int(number * 1000000))

    # plain number
    v = v.replace(",", "").replace(" ", "").strip()
    number_match = re.search(r"\d+(?:\.\d+)?", v)
    if number_match:
        try:
            return str(int(float(number_match.group())))
        except ValueError:
            pass

    raise ValueError(f'Could not parse budget: "{original_v}"')


def parse_and_validate_budget(value: str) -> ValidatorResult:
    """Parse and validate budget. Returns (normalized_value, error)."""
    try:
        normalized = parse_budget_string(value)
        return normalized, None
    except ValueError:
        return None, "Could not parse budget. Please provide a numeric value."


def validate_duration(value: int | str) -> ValidatorResult:
    """Validate duration in days. Returns (normalized_value, error)."""
    try:
        days = int(value)
        if days <= 0:
            return None, "Duration must be a positive number"
        if days > 365:
            return None, "Duration cannot exceed 365 days"
        return days, None
    except (ValueError, TypeError):
        return None, "Duration must be a valid number of days"


PLATFORM_ALIASES = {
    "google": "google",
    "google ads": "google",
    "meta": "meta",
    "facebook": "meta",
    "fb": "meta",
    "meta ads": "meta",
    "instagram": "meta",
}


def validate_platform(value: str) -> ValidatorResult:
    """Validate and normalize platform choice."""
    normalized = str(value).strip().lower()
    result = PLATFORM_ALIASES.get(normalized)
    if result:
        return result, None
    return None, "Please specify 'google' or 'meta' as the platform"


VALIDATORS = {
    "validate_website": validate_website,
    "parse_and_validate_budget": parse_and_validate_budget,
    "validate_duration": validate_duration,
    "validate_platform": validate_platform,
}
