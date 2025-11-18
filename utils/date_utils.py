from datetime import datetime

def format_duration_clause(duration: str) -> str:
    """Convert duration text or range into SQL-compatible clause.
    Automatically swaps dates if out of order.
    """
    if "," in duration:
        start_raw, end_raw = [d.strip() for d in duration.split(",")]

        def normalize(d):
            if "/" in d:
                return datetime.strptime(d, "%d/%m/%Y")
            elif "-" in d:
                return datetime.strptime(d, "%Y-%m-%d")
            raise ValueError(f"Unsupported date format: {d}")

        start_date = normalize(start_raw)
        end_date = normalize(end_raw)

        # Swap if reversed
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # Format as SQL-friendly date strings
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        return f"BETWEEN '{start_str}' AND '{end_str}'"
    else:
        return f"DURING {duration}"