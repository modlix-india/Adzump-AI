from datetime import datetime


def format_duration_clause(duration: str) -> str:
    """Convert duration text or range into SQL-compatible clause."""
    if "," in duration:
        start_raw, end_raw = [d.strip() for d in duration.split(",")]

        def normalize(d):
            if "/" in d:
                return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
            elif "-" in d:
                return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d")
            return d

        start_date = normalize(start_raw)
        end_date = normalize(end_raw)
        return f"BETWEEN '{start_date}' AND '{end_date}'"
    else:
        return f"DURING {duration}"
