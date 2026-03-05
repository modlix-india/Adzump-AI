"""Field Registry - Single source of truth for ad plan fields."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FieldDef:
    """Definition for an ad plan field."""

    type: type
    description: str
    validator: Optional[str] = None
    error_msg: Optional[str] = None
    required: bool = True


FIELD_REGISTRY: dict[str, FieldDef] = {
    "platform": FieldDef(
        type=str,
        description="Advertising platform: 'google' or 'meta'",
        validator="validate_platform",
        error_msg="Please specify 'google' or 'meta' as the platform",
        required=True,
    ),
    "businessName": FieldDef(
        type=str,
        description="Name of the business/company",
        required=True,
    ),
    "websiteURL": FieldDef(
        type=str,
        description="Website URL (e.g., example.com or https://example.com)",
        validator="validate_website",
        error_msg="Please provide a valid URL like example.com or https://example.com",
        required=True,
    ),
    "budget": FieldDef(
        type=str,
        description="Daily advertising budget (numeric value, e.g., 5000 or 5k)",
        validator="parse_and_validate_budget",
        error_msg="Please provide budget as a number, e.g. 5000 or 5k",
        required=False,
    ),
    "durationDays": FieldDef(
        type=int,
        description="Campaign duration in days (numeric value, e.g., 7 or 14)",
        validator="validate_duration",
        error_msg="How many days should the campaign run? e.g. 7 or 14",
    ),
    "targetLeads": FieldDef(
        type=int,
        description="Target number of leads/conversions for Google campaigns (e.g., 50 or 100)",
        validator="validate_target_leads",
        error_msg="Please provide a number of leads, e.g. 50 or 100",
        required=False,
    ),
}

REQUIRED_FIELDS = tuple[str, ...](k for k, v in FIELD_REGISTRY.items() if v.required)
