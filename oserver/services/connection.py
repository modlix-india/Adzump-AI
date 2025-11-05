import os
import requests
from oserver.utils.helpers import get_base_url


def fetch_google_api_token_simple(client_code: str, appcode: str = None) -> str:
    base = get_base_url()
    url = f"{base}/api/core/connections/internal/oauth2/token/GOOGLE_API"
    headers = {
        # match the cURL header names exactly
        "appcode": appcode or os.getenv("APPCODE", "marketingai"),
        "clientcode": client_code,
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    try:
        data = resp.json()
        token = (
                data.get("access_token")
                or data.get("token")
                or data.get("id_token")
        )
        return token if token is not None else resp.text.strip()
    except ValueError:
        return resp.text.strip()
