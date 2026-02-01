import os
from typing import Optional

import requests

from oserver.utils.helpers import get_base_url


def fetch_oauth_token(
    client_code: str,
    connection_name: str,
    appcode: Optional[str] = None,
) -> str:
    """Fetch OAuth token from connection service by connection name."""
    base = get_base_url()
    url = f"{base}/api/core/connections/internal/oauth2/token/{connection_name}"
    resolved_appcode = appcode or os.getenv("APPCODE") or "marketingai"
    headers = {
        "appcode": resolved_appcode,
        "clientcode": client_code,
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    try:
        data = resp.json()
        token = data.get("access_token") or data.get("token") or data.get("id_token")
        return token if token is not None else resp.text.strip()
    except ValueError:
        return resp.text.strip()


def fetch_google_api_token_simple(
    client_code: str,
    appcode: Optional[str] = None,
) -> str:
    """Fetch Google API OAuth token."""
    return fetch_oauth_token(client_code, "GOOGLE_API", appcode)


def fetch_meta_api_token(
    client_code: str,
    appcode: Optional[str] = None,
) -> str:
    """Fetch Meta API OAuth token."""
    return fetch_oauth_token(client_code, "META_API", appcode)
