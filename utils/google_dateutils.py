import structlog
from typing import Optional
from datetime import datetime

logger = structlog.get_logger(__name__)

# Google Ads supported date enums
VALID_DATE_ENUMS = {
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_BUSINESS_WEEK",
    "THIS_WEEK_SUN_TODAY",
    "THIS_WEEK_MON_TODAY",
    "LAST_WEEK_SUN_SAT",
    "LAST_WEEK_MON_SUN",
    "THIS_MONTH",
    "LAST_MONTH",
}


def format_date_range(duration: Optional[str]) -> Optional[str]:
    """GAQL segments.date clause: enum or range (DD/MM/YYYY or YYYY-MM-DD)."""
    if not duration:
        return None

    dur = duration.strip().upper()

    if "," in dur:
        try:
            start_raw, end_raw = [d.strip() for d in dur.split(",", 1)]
            for fmt in ["%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    start = datetime.strptime(start_raw, fmt).strftime("%Y-%m-%d")
                    end = datetime.strptime(end_raw, fmt).strftime("%Y-%m-%d")
                    if datetime.strptime(start, "%Y-%m-%d") > datetime.strptime(
                        end, "%Y-%m-%d"
                    ):
                        raise ValueError("Start date after end date")
                    return f"segments.date BETWEEN '{start}' AND '{end}'"
                except ValueError:
                    continue
            raise ValueError("Invalid date format")
        except ValueError as e:
            logger.warning("Date range error", duration=duration, error=str(e))
            return None

    elif dur in VALID_DATE_ENUMS:
        return f"segments.date DURING {dur}"
    else:
        logger.warning(
            "Invalid date enum", duration=duration, valid_enums=list(VALID_DATE_ENUMS)
        )
        return None
