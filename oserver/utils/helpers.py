from datetime import datetime
from urllib.parse import urlparse
import os
import re

def get_base_url() -> str:
    """Return base URL from environment or default."""
    return os.getenv("NOCODE_PLATFORM_HOST", "https://dev.adzump.ai").rstrip("/")


def generate_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    business_name = re.sub(r"\.(com|net|org|in|co|io|ai|info|biz|gov|edu)$", "", domain)
    business_name = business_name.replace(".", "_")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{business_name}_{now}.png"