import os
import re
import textwrap
from openai import OpenAI


def setup_apis():
    try:
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OPENAI_API_KEY is required")
        openai_client = OpenAI(api_key=openai_key)

        developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        if not developer_token:
            raise ValueError("GOOGLE_ADS_DEVELOPER_TOKEN is required")
        return openai_client
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Failed to setup APIs: %s", e)
        raise


def normalize_text(kw: str) -> str:
    if kw is None:
        return ""
    return re.sub(r"\s+", " ", str(kw).strip()).lower()


def safe_truncate_to_sentence(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    try:
        return textwrap.shorten(text, width=limit, placeholder="...")
    except Exception:
        return text[:limit] + "..."
    
def get_safety_patterns():
    return [
        re.compile(r"http[s]?://", re.IGNORECASE),
        re.compile(r"\.com", re.IGNORECASE),
        re.compile(r"\.net", re.IGNORECASE),
        re.compile(r"\.org", re.IGNORECASE),
        re.compile(r"^\d+$"),
        re.compile(r"(xxx|porn|adult|sex)", re.IGNORECASE),
        re.compile(r"^\s*$")
    ]


def get_fallback_negative_keywords():
    """Return the default fallback negative keywords list for keyword filtering."""
    return [
        {"keyword": "free", "reason": "Universal budget protection"},
        {"keyword": "cheap", "reason": "Universal budget protection"},
        {"keyword": "jobs", "reason": "Universal intent filter - employment"},
        {"keyword": "career", "reason": "Universal intent filter - employment"},
        {"keyword": "hiring", "reason": "Universal intent filter - employment"},
        {"keyword": "salary", "reason": "Universal intent filter - employment"},
        {"keyword": "tutorial", "reason": "Universal informational filter"},
        {"keyword": "how to", "reason": "Universal informational filter"},
        {"keyword": "guide", "reason": "Universal informational filter"},
        {"keyword": "pdf", "reason": "Universal informational filter"},
        {"keyword": "download", "reason": "Universal informational filter"},
        {"keyword": "wiki", "reason": "Universal informational filter"},
        {"keyword": "youtube", "reason": "Universal platform filter"},
        {"keyword": "video", "reason": "Universal media filter"},
        {"keyword": "images", "reason": "Universal media filter"},
        {"keyword": "used", "reason": "Universal condition filter"},
        {"keyword": "second hand", "reason": "Universal condition filter"},
        {"keyword": "refurbished", "reason": "Universal condition filter"},
        {"keyword": "broken", "reason": "Universal condition filter"},
        {"keyword": "repair", "reason": "Universal service type filter"},
    ]
