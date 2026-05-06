from datetime import date, datetime, timedelta
from core.models.meta_constants import SCHEDULE_BUFFER_SECONDS
from core.models.meta import AdCreationStage


def normalize_time(value: str | date | datetime | None) -> str | None:
    """Normalize a date to Meta's ISO-8601 format.
 
    Handle 'Today' by adding a safety buffer, and 'Future' by defaulting 
    to midnight local time.
    """
    if not value:
        return None

    try:
        if isinstance(value, (date, datetime)):
            parsed_date = value if isinstance(value, date) else value.date()
        else:
            parsed_date = datetime.fromisoformat(value).date()

        today = datetime.now().date()

        if parsed_date == today:
            # Add requirement buffer + 10s extra padding for network/processing latency
            dt = datetime.now().astimezone() + timedelta(
                seconds=SCHEDULE_BUFFER_SECONDS + 10
            )
        else:
            dt = datetime.combine(parsed_date, datetime.min.time()).astimezone()

        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    except (ValueError, TypeError):
        raise ValueError(f"Invalid date format: '{value}'. Expected YYYY-MM-DD.")


def build_name(
    name: str, entity_type: AdCreationStage, target_date: datetime | None = None
) -> str:
    """Generate a standardized name for Meta entities."""
    # Format: 'Project - Campaign 24/05/26'
    if not isinstance(entity_type, AdCreationStage):
        try:
            entity_type = AdCreationStage(entity_type.upper().strip())
        except ValueError:
            raise ValueError(
                f"Invalid entity_type '{entity_type}'. Must be a valid AdCreationStage."
            )

    if target_date is None:
        target_date = datetime.today()

    date_str = target_date.strftime("%d/%m/%y")
    label = entity_type.value.capitalize()

    return f"{name} - {label} {date_str}"
