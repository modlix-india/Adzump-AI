from datetime import datetime, timedelta
from typing import Optional
from agents.meta.payload_builders.constants import SCHEDULE_BUFFER_SECONDS


def normalize_time(date_str: Optional[str]) -> Optional[str]:
    """
    Normalizes a date-only string (YYYY-MM-DD) to Meta's accepted format.
    Meta format: YYYY-MM-DDTHH:MM:SS±HHMM e.g. "2026-03-21T00:00:00+0530"

    - Today  → now + buffer
    - Future → midnight local time
    """
    if not date_str:
        return None

    try:
        parsed_date = datetime.fromisoformat(date_str).date()
        today       = datetime.now().date()

        if parsed_date == today:
            dt = datetime.now().astimezone() + timedelta(seconds=SCHEDULE_BUFFER_SECONDS + 10)
        else:
            dt = datetime.combine(parsed_date, datetime.min.time()).astimezone()

        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    except ValueError:
        return date_str  # let validate_schedule raise 400


def build_name(name: str, entity_type: str, date: datetime = None) -> str:
    """
    Formatted string e.g., "name - entity_type dd/mm/yy"
    """
    ENTITY_LABELS = {
        "campaign": "Campaign",
        "adset":    "Adset",
        "creative": "Creative",
        "ad":       "Ad",
    }

    entity_type = entity_type.lower().strip()
    
    if entity_type not in ENTITY_LABELS:
        raise ValueError(f"Invalid entity_type '{entity_type}'. Must be one of: {list(ENTITY_LABELS.keys())}")

    if date is None:
        date = datetime.today()

    date_str = date.strftime("%d/%m/%y")
    label = ENTITY_LABELS[entity_type]

    return f"{name} - {label} {date_str}"