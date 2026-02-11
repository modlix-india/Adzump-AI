import re
from datetime import datetime, timedelta
from typing import Tuple
from urllib.parse import urlparse, urlunparse
import dns.resolver


def get_today_end_date_with_duration(duration_days):
    """Calculate start and end dates based on duration."""
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=duration_days)
    return {
        "startDate": start_date.strftime("%d/%m/%Y"),
        "endDate": end_date.strftime("%d/%m/%Y"),
    }


async def validate_domain_exists(url: str) -> Tuple[bool, str]:
    """
    validate if domain exists.
    Returns: (is_valid,error_message)
    """
    try:
        domain = urlparse(url).hostname or url
        domain = re.sub(r"^https?://(www\.)?", "", domain, flags=re.IGNORECASE)
        domain = domain.split("/")[0]
        domain = domain.encode("idna").decode("ascii")

        resolver = dns.resolver.Resolver()
        resolver.timeout = 3
        resolver.lifetime = 3
        try:
            resolver.resolve(domain, "A")
            return True, ""
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            resolver.resolve(domain, "AAAA")
            return True, ""
    except dns.resolver.NXDOMAIN:
        return False, f"The domain '{domain}' does not exist. Please check the URL."
    except dns.resolver.NoAnswer:
        return (
            False,
            f"This domain '{domain}' has no DNS records.Please verify the URL.",
        )
    except dns.resolver.Timeout:
        return True, ""
    except Exception:
        return False, f"Invalid domain '{domain}'. Please check the URL."


def normalize_url(url: str) -> str:
    if not url:
        return url

    # Trim outer spaces
    url = url.strip()

    # Remove trailing slashes
    url = url.rstrip("/")

    # Parse URL
    parsed = urlparse(url)

    # Lowercase only the domain
    netloc = parsed.netloc.lower()

    # Remove duplicate slashes in path
    path = "/".join(filter(None, parsed.path.split("/")))

    # Rebuild URL
    normalized = urlunparse(
        (
            parsed.scheme,
            netloc,
            f"/{path}" if path else "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    return normalized


def join_url(base, path):
    if not path:
        return ""
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if base and path else path


def micros_to_rupees(micros) -> float:
    return round(float(micros) / 1_000_000, 2)
