import os
import re
import textwrap
from openai import OpenAI
from urllib.parse import urlparse


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

# ---------------- Helper: Check if link is internal ---------------- #
def is_internal_link(href: str, base_domain: str) -> bool:
    """Return True if href belongs to the same domain, subdomain, or is relative."""
    if not href or href.startswith(("javascript:void(0)", "tel:")):
        return False

    parsed = urlparse(href)
    if not parsed.netloc:  # relative or hash (#gallery, /about)
        return True

    href_domain = parsed.netloc.replace("www.", "").lower()
    return base_domain in href_domain