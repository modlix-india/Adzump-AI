import httpx
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from fastapi import HTTPException
from oserver.services.connection import fetch_google_api_token_simple


GOOGLE_ADS_API_VERSION = "v22"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
REQUEST_TIMEOUT_SECONDS = 30
MICROS_PER_UNIT = 1_000_000


# SHARED HTTP CLIENT
_http_client: Optional[httpx.AsyncClient] = None

async def init_http_client() -> None:
    global _http_client
    _http_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)

async def close_http_client() -> None:
    if _http_client:
        await _http_client.aclose()

def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("HTTP client not initialized")
    return _http_client

# GOOGLE ADS CONTEXT
@dataclass(frozen=True)
class GoogleAdsContext:
    access_token: str
    developer_token: str
    login_customer_id: str


def build_headers(context: GoogleAdsContext) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {context.access_token}",
        "developer-token": context.developer_token,
        "login-customer-id": context.login_customer_id,
        "Content-Type": "application/json",
    }

# CREDENTIALS
def resolve_google_ads_credentials(client_code: str) -> Dict[str, str]:
    if not client_code:
        raise ValueError("client_code is required")

    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    access_token = fetch_google_api_token_simple(client_code)

    if not developer_token or not access_token:
        raise RuntimeError("Failed to resolve Google Ads credentials")

    return {
        "access_token": access_token,
        "developer_token": developer_token,
    }

# GAQL EXECUTION
async def execute_gaql_search(customer_id: str,gaql_query: str,context: GoogleAdsContext) -> List[Dict]:

    http_client = get_http_client()

    url = f"{GOOGLE_ADS_BASE_URL}/customers/{customer_id}/googleAds:search"

    response = await http_client.post(
        url,
        headers=build_headers(context),
        json={"query": gaql_query},
    )

    response_body = response.json()

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail={
                "source": "google_ads_api",
                "type": "api_error",
                "customer_id": customer_id,
                "login_customer_id": context.login_customer_id,
                "gaql": gaql_query.strip(),
                "google_ads_error": response_body,
            },
        )

    return response_body.get("results", [])

# MCC CHILD ACCOUNTS
async def fetch_direct_child_customers(manager_customer_id: str,context: GoogleAdsContext) -> List[str]:

    query = """
        SELECT customer_client.id
        FROM customer_client
        WHERE customer_client.level = 1
          AND customer_client.manager = FALSE
    """

    results = await execute_gaql_search(
        manager_customer_id, query, context
    )

    return [row["customerClient"]["id"] for row in results]

# CAMPAIGN TARGET LOCATIONS
async def fetch_enabled_campaign_location_targets(customer_id: str,context: GoogleAdsContext) -> Dict[str, Dict]:

    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign_criterion.location.geo_target_constant
        FROM campaign_criterion
        WHERE campaign.status = ENABLED
          AND campaign_criterion.type = LOCATION
          AND campaign_criterion.negative = FALSE
    """

    results = await execute_gaql_search(
        customer_id, query, context
    )

    campaign_targets: Dict[str, Dict] = {}

    for row in results:

        campaign_id = row["campaign"]["id"]

        campaign_targets.setdefault(
            campaign_id,
            {
                "campaign_id": campaign_id,
                "campaign_name": row["campaign"]["name"],
                "targeted_locations": set(),
            },
        )

        geo_constant = row["campaignCriterion"]["location"].get(
            "geoTargetConstant"
        )

        if geo_constant:
            campaign_targets[campaign_id][
                "targeted_locations"
            ].add(geo_constant)

    return campaign_targets

# LOCATION PERFORMANCE
async def fetch_location_performance_metrics(customer_id: str,context: GoogleAdsContext) -> Dict[str, Dict]:

    query = """
        SELECT
          campaign.id,
          location_view.resource_name,
          campaign_criterion.location.geo_target_constant,
          metrics.impressions,
          metrics.clicks,
          metrics.conversions,
          metrics.conversions_value,
          metrics.cost_micros
        FROM location_view
        WHERE campaign.status = ENABLED
          AND metrics.impressions > 0
          AND segments.date DURING LAST_30_DAYS
    """

    results = await execute_gaql_search(
        customer_id, query, context
    )

    campaign_geo_metrics: Dict[str, Dict] = {}

    for row in results:

        geo_constant = None

        criterion = row.get("campaignCriterion")

        if criterion:
            location = criterion.get("location")
            if location and location.get("geoTargetConstant"):
                geo_constant = location["geoTargetConstant"]

        if not geo_constant:
            resource_name = row.get(
                "locationView", {}
            ).get("resourceName")

            if resource_name and "~" in resource_name:
                geo_id = resource_name.rsplit("~", 1)[-1]
                geo_constant = f"geoTargetConstants/{geo_id}"

        if not geo_constant:
            continue

        metrics = row["metrics"]
        campaign_id = row["campaign"]["id"]

        cost_micros = int(metrics.get("costMicros", 0))

        campaign_geo_metrics.setdefault(
            campaign_id, {}
        )[geo_constant] = {
            "impressions": int(metrics.get("impressions", 0)),
            "clicks": int(metrics.get("clicks", 0)),
            "conversions": float(
                metrics.get("conversions", 0)
            ),
            "conversions_value": float(
                metrics.get("conversionsValue", 0)
            ),
            "cost_micros": cost_micros,
            "cost": round(
                cost_micros / MICROS_PER_UNIT, 2
            ),
        }

    return campaign_geo_metrics

# GEO DETAILS
async def fetch_geo_target_details(customer_id: str,geo_constants: List[str],context: GoogleAdsContext) -> Dict[str, Dict]:

    if not geo_constants:
        return {}

    geo_list = ", ".join(f"'{g}'" for g in geo_constants)

    query = f"""
        SELECT
          geo_target_constant.resource_name,
          geo_target_constant.name,
          geo_target_constant.country_code,
          geo_target_constant.target_type
        FROM geo_target_constant
        WHERE geo_target_constant.resource_name IN ({geo_list})
    """

    results = await execute_gaql_search(
        customer_id, query, context
    )

    geo_details_map = {}

    for row in results:

        resource_name = row["geoTargetConstant"][
            "resourceName"
        ]

        geo_details_map[resource_name] = {
            "geo_target_constant": resource_name,
            "location_name": row["geoTargetConstant"]["name"],
            "country_code": row["geoTargetConstant"][
                "countryCode"
            ],
            "location_type": row["geoTargetConstant"][
                "targetType"
            ],
        }

    return geo_details_map

def evaluate_location_performance(
    campaign_data: Dict,
    geo_metrics: Dict[str, Dict],
    spend_threshold_micros: int = 10_000_000,
):

    REMOVE_CLICKS = 50

    locations_to_remove = []
    locations_to_add = []

    targeted_locations = campaign_data["targeted_locations"]

    for geo_constant, metrics in geo_metrics.items():

        # SAFETY → IGNORE IF GEO CONSTANT MISSING
        if not geo_constant:
            continue

        conversions = metrics["conversions"]
        clicks = metrics["clicks"]
        cost_micros = metrics["cost_micros"]

        # TARGETED → REMOVE PROVEN WASTE SPEND
        if geo_constant in targeted_locations:

            if (
                conversions == 0
                and clicks >= REMOVE_CLICKS
                and cost_micros > spend_threshold_micros
            ):
                locations_to_remove.append(
                    {
                        "geo_target_constant": geo_constant,
                        "metrics": metrics,
                        "action": "remove",
                        "reason": "High spend & clicks but zero conversions",
                    }
                )
        # UNTARGETED → ADD IF CONVERSIONS EXIST
        else:

            if conversions > 0:
                locations_to_add.append(
                    {
                        "geo_target_constant": geo_constant,
                        "metrics": metrics,
                        "action": "add",
                        "reason": "Conversions from non-targeted location",
                    }
                )

        # Everything else ignored

    return locations_to_remove, locations_to_add


# MAIN SERVICE
async def optimize_locations_for_client(
    client_code: str,
    login_customer_id: str,
) -> List[Dict]:

    credentials = resolve_google_ads_credentials(
        client_code
    )

    context = GoogleAdsContext(
        access_token=credentials["access_token"],
        developer_token=credentials["developer_token"],
        login_customer_id=login_customer_id,
    )

    child_customer_ids = await fetch_direct_child_customers(
        login_customer_id, context
    )

    optimization_results = []

    for child_customer_id in child_customer_ids:

        campaign_targets = (
            await fetch_enabled_campaign_location_targets(
                child_customer_id, context
            )
        )

        campaign_metrics = (
            await fetch_location_performance_metrics(
                child_customer_id, context
            )
        )

        all_geo_constants = list(
            {
                geo
                for metrics in campaign_metrics.values()
                for geo in metrics.keys()
            }
        )

        geo_details_map = await fetch_geo_target_details(
            child_customer_id,
            all_geo_constants,
            context,
        )

        campaign_results = []

        for campaign_id, campaign_data in campaign_targets.items():

            if campaign_id not in campaign_metrics:
                continue

            optimize_list, recommend_list = (
                evaluate_location_performance(
                    campaign_data,
                    campaign_metrics[campaign_id],
                )
            )

            location_actions = []

            def build_action(item, action):

                geo_constant = item[
                    "geo_target_constant"
                ]

                geo_object = geo_details_map.get(
                    geo_constant,
                    {
                        "geo_target_constant": geo_constant,
                        "location_name": "Unknown",
                        "country_code": None,
                        "location_type": None,
                    },
                )

                return {
                    "action": action,
                    "geo": geo_object,
                    "metrics": item["metrics"],
                    "reason": item["reason"],
                }

            for item in optimize_list:
                location_actions.append(
                    build_action(item, item["action"])
                )

            for item in recommend_list:

                geo_constant = item["geo_target_constant"]

                geo_object = geo_details_map.get(
                    geo_constant,
                    {
                        "geo_target_constant": geo_constant,
                        "location_name": "Unknown",
                        "country_code": None,
                        "location_type": None,
                    },
                )

                #Skip ADD if location name missing / unknown
                if (
                    not geo_object.get("location_name")
                    or geo_object["location_name"] == "Unknown"
                ):
                    continue

                location_actions.append(
                    build_action(item, item["action"])
                )

            if location_actions:
                campaign_results.append(
                    {
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_data[
                            "campaign_name"
                        ],
                        "location_actions": location_actions,
                    }
                )

        if campaign_results:
            optimization_results.append(
                {
                    "mcc_customer_id": login_customer_id,
                    "customer_id": child_customer_id,
                    "campaigns": campaign_results,
                }
            )

    return optimization_results
