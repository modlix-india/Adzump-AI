import logging
import httpx
from typing import List, Dict, Optional, Any
from datetime import datetime
from utils import httpx_utils
from third_party.google.google_utils import keyword_utils
from third_party.google.models.keyword_model import Keyword

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_DELAY = 5
BASEURL = "https://googleads.googleapis.com"
APIVERSION = "v21"


# Google Ads supported date enums
VALID_DATE_ENUMS = {
    "TODAY", "YESTERDAY",
    "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_BUSINESS_WEEK",
    "THIS_WEEK_SUN_TODAY", "THIS_WEEK_MON_TODAY",
    "LAST_WEEK_SUN_SAT", "LAST_WEEK_MON_SUN",
    "THIS_MONTH", "LAST_MONTH"
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
                    if datetime.strptime(start, "%Y-%m-%d") > datetime.strptime(end, "%Y-%m-%d"):
                        raise ValueError("Start date after end date")
                    return f"segments.date BETWEEN '{start}' AND '{end}'"
                except ValueError:
                    continue
            raise ValueError("Invalid date format")
        except ValueError as e:
            logger.warning(f"Date range error in '{duration}': {e}")
            return None
    
    elif dur in VALID_DATE_ENUMS:
        return f"segments.date DURING {dur}"
    else:
        logger.warning(f"Invalid enum '{duration}'. Valid: {', '.join(VALID_DATE_ENUMS)}")
        return None

async def execute_google_ads_query(
    customer_id: str,
    login_customer_id: str,
    access_token: str,
    developer_token: str,
    query: str,
    retry_attempts: int = RETRY_ATTEMPTS,
    use_stream: bool = True,
    api_version: str = APIVERSION,
) -> List[Dict]:
    """Execute a Google Ads query with retry logic.(query endpoints only)"""
    endpoint_type = "searchStream" if use_stream else "search"
    endpoint = f"{BASEURL}/{api_version}/customers/{customer_id}/googleAds:{endpoint_type}"
    
    headers = {
        "authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "content-type": "application/json",
        "login-customer-id": login_customer_id
    }
    
    client = await httpx_utils.get_http_client()

    logger.info(f"Executing GAQL query using endpoint {endpoint_type}")

    response = await keyword_utils.retry_post_with_backoff(
        client=client,
        endpoint=endpoint,
        headers=headers,
        payload={"query": query},
        max_attempts=retry_attempts,
        base_delay=RETRY_DELAY
    )
    
    data = response.json()
    
    if use_stream:
        # SearchStream returns array of batches: [{results: [...], fieldMask: ...}, ...]
        results = []
        if isinstance(data, list):
            for batch in data:
                results.extend(batch.get('results', []))
        else:
            # Fallback if API changes (shouldn't happen)
            logger.warning("SearchStream returned non-list response")
            results = data.get('results', [])
    else:
        # Search returns single object: {results: [...], nextPageToken: ...}
        results = data.get('results', [])
        next_page_token = data.get('nextPageToken')
        if next_page_token:
            logger.warning(f"Results paginated. Use SearchStream or implement pagination for token: {next_page_token}")
    
    logger.info(f"Retrieved {len(results)} rows")
    return results


async def execute_google_ads_service_call(
    customer_id: str,
    login_customer_id: str,
    access_token: str,
    developer_token: str,
    service_method: str,
    payload: Dict[str, Any],
    api_version: str = APIVERSION,
    retry_attempts: int = RETRY_ATTEMPTS,
) -> Dict[str, Any]:
    ''' Execute a Google Ads service method call (non-query endpoints).'''

    # Add colon prefix for REST endpoint
    endpoint = f"{BASEURL}/{api_version}/customers/{customer_id}:{service_method}"
    
    headers = {
        "authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "content-type": "application/json",
        "login-customer-id": login_customer_id
    }
    
    client = await httpx_utils.get_http_client()
    
    logger.info(f"Executing service method: {service_method}")
    
    response = await keyword_utils.retry_post_with_backoff(
        client=client,
        endpoint=endpoint,
        headers=headers,
        payload=payload,
        max_attempts=retry_attempts,
        base_delay=RETRY_DELAY
    )
    
    data = response.json()
    logger.info(f"Service call completed for {service_method}")
    return data


def group_keywords_by_ad_group(keywords: List[Keyword]) -> Dict[str,Dict[str, Any]]:
    grouped = {}
    for kw in keywords:
        ad_group_id = kw.ad_group_id
        if ad_group_id not in grouped:
            grouped[ad_group_id] = {
                "ad_group_name": kw.ad_group_name,
                "keywords": []
            }
        grouped[ad_group_id]["keywords"].append(kw)
    return grouped