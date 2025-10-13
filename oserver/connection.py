import os
import requests


def fetch_google_api_token_simple(client_code: str, appcode: str = None) -> str:
    base = (os.getenv("NOCODE_PLATFORM_HOST") or "").rstrip("/")
    if not base:
        raise RuntimeError("NOCODE_PLATFORM_HOST is not set")

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
    


def fetch_product_details(data_object_id: str,access_token:str, client_code:str):

    base = (os.getenv("NOCODE_PLATFORM_HOST") or "").rstrip("/")
    if not base:
        raise RuntimeError("NOCODE_PLATFORM_HOST is not set")
    
    url = f"{base}/api/core/function/execute/CoreServices.Storage/Read"

    headers = {
        "authorization": access_token,
        "content-type": "application/json",
        "clientCode": client_code,
        "appcode": "marketingai"
    }

    payload = {
        "storageName": "AISuggestedData",
        "appCode": "marketingai",
        "dataObjectId": data_object_id,
        "eager": False,
        "eagerFields": []
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching product details: {e}")
        return None
