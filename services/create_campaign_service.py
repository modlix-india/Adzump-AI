# services/campaign_service.py
from typing import Any, Dict
from third_party.google.services.google_ads_client import post_mutate_operations, GoogleAdsClientError
from services.build_ads_payload import generate_google_ads_mutate_operations


class CampaignServiceError(Exception):
    pass


async def create_and_post_campaign(
    request_body: Dict[str, Any],
    client_code: str,
    api_version: str = "v20",
) -> Dict[str, Any]:
    """
    1. Build mutate payload using generate_google_ads_mutate_operations
    2. Post payload to Google Ads via google_ads_client
    """
    # Validate presence of required fields from request_body
    customer_id = request_body.get("customer_id") or request_body.get("customerId")
    login_customer_id = request_body.get("login_customer_id") or request_body.get("loginCustomerId") or request_body.get("login-customer-id")

    if not customer_id:
        raise CampaignServiceError("customer_id is required in the request payload")

    if not login_customer_id:
        raise CampaignServiceError(
            "login_customer_id is required in the request payload (key: login_customer_id or loginCustomerId or login-customer-id)"
        )

    # Build mutate payload using your existing generator
    mutate_payload = generate_google_ads_mutate_operations(customer_id=customer_id, ads=request_body)
    
    # Post to Google Ads
    try:
        response = await post_mutate_operations(
            customer_id=customer_id,
            login_customer_id=str(login_customer_id),
            mutate_payload=mutate_payload,
            client_code=client_code,
            api_version=api_version,
        )
    except GoogleAdsClientError as e:
        raise CampaignServiceError(str(e))

    return response
