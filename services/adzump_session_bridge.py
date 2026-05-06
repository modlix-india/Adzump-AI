"""Bridge ds sessions ↔ nocode-ai adzump sessions.

Until the adzump migration is complete, the chat happens in nocode-ai
(adzump agent) but downstream APIs (keywords, campaign create, ads) still
run in ds and expect a populated `sessions[id]["campaign_data"]`. This
module pulls the adzump session from nocode-ai and seeds a ds session.

Flow:
1. UI / caller has an adzump session id (e.g. "SYSTEM_165db4b8") and a JWT.
2. Calls POST /api/ds/chat/from-adzump-session/{id} on ds with auth headers.
3. ds calls GET {gateway}/marketingai/{clientCode}/api/ai/adzump/sessions/{id}
   forwarding the user's auth — same trust boundary as the original request.
4. ds parses session.context_json, maps adzump fields → ds campaign_data,
   creates a ds session, returns the new ds session_id.

Mapping nocode-ai → ds (see CampaignData in models/campaign_data_model.py
plus actual usages in chat_service / google_keywords_service):

| ds key              | adzump source                                |
|---------------------|----------------------------------------------|
| businessName        | product_data.product_name                    |
| websiteURL          | product_profile.url or pages_analyzed[0]     |
| budget              | campaign_spec.budget (digits extracted)      |
| durationDays        | campaign_spec.duration (digits extracted)    |
| loginCustomerId     | campaign_spec.parent_account                 |
| customerId          | campaign_spec.account                        |
| locations           | [_location_meta.address] or [spec.location]  |
| platform            | campaign_spec.platform                       |
| productSummary      | product_data.summary                         |
| competitors         | competitor_analysis.competitors              |
| adzumpProductId     | session.context["product_id"]                |
| adzumpSessionId     | source session id                            |

Meta-only fields (fb_page, ig_page) are passed through under their adzump
keys but not mapped to a typed CampaignData field — ds's Meta path can
read them off the dict directly when needed.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from structlog import get_logger  # type: ignore

from core.infrastructure.context import auth_context
from exceptions.custom_exceptions import BusinessValidationException
from oserver.services.base_api_service import BaseAPIService
from oserver.utils.helpers import get_base_url
from services.session_manager import sessions

logger = get_logger(__name__)

# AppCode under which adzump records live in nocode-ai (matches the gateway
# routing prefix `/marketingai/{clientCode}/...`).
ADZUMP_APP_CODE = "marketingai"


# ── Outbound: fetch adzump session from nocode-ai ────────────────────────


async def _fetch_adzump_session(
    adzump_session_id: str,
    *,
    access_token: str,
    client_code: str,
    x_forwarded_host: str = "",
    x_forwarded_port: str = "",
) -> dict[str, Any]:
    """GET the adzump session detail through the gateway.

    Returns the parsed JSON response (which has shape
    ``{session, history, total_history, limit, offset}``).
    Raises BusinessValidationException on HTTP error or empty response.
    """
    base = get_base_url().rstrip("/")
    url = f"{base}/{ADZUMP_APP_CODE}/{client_code}/api/ai/adzump/sessions/{adzump_session_id}"
    # Ds's AuthContextMiddleware strips the "Bearer " prefix on inbound, so
    # access_token is a bare JWT here. Saas's securityContextAuthentication
    # filter rejects bare tokens — always prefix on the way out.
    bearer = access_token if access_token.lower().startswith("bearer ") else f"Bearer {access_token}"
    headers = {
        "authorization": bearer,
        "clientCode": client_code,
        "appCode": ADZUMP_APP_CODE,
        "X-Forwarded-Host": x_forwarded_host or "",
        "X-Forwarded-Port": x_forwarded_port or "",
        "content-type": "application/json",
    }

    client = BaseAPIService()
    try:
        result = await client.request("GET", url, headers=headers)
    except Exception as e:
        logger.warning("adzump_session_fetch_failed",
                       url=url, err=str(e)[:200])
        raise BusinessValidationException(
            f"Failed to fetch adzump session {adzump_session_id}: {e}",
        ) from e

    if not isinstance(result, dict) or "session" not in result:
        raise BusinessValidationException(
            f"Unexpected response shape from nocode-ai: {type(result).__name__}",
        )
    return result


# ── Mapping: adzump context → ds campaign_data ────────────────────────────


_DIGITS_RE = re.compile(r"\d+")


def _extract_int(value: Any) -> Optional[int]:
    """Pull the first integer out of a possibly-formatted string.

    "60 days" → 60, "₹25,000/day" → 25000, 30 → 30, None → None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(_DIGITS_RE.findall(str(value)))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _resolve_url(context: dict) -> str:
    profile = context.get("product_profile") or {}
    if profile.get("url"):
        return str(profile["url"])
    product = context.get("product_data") or {}
    pages = product.get("pages_analyzed") or []
    if pages:
        return str(pages[0])
    return ""


def _resolve_locations(context: dict) -> list[str]:
    meta = context.get("_location_meta") or {}
    if meta.get("address"):
        return [str(meta["address"])]
    spec = context.get("campaign_spec") or {}
    if spec.get("location"):
        return [str(spec["location"])]
    return []


def _strip_account_id(value: Any) -> Optional[str]:
    """Account ids should be stored without dashes/whitespace."""
    if value is None:
        return None
    s = str(value).strip()
    return re.sub(r"[\s\-]", "", s) or None


def map_adzump_context_to_campaign_data(context: dict) -> dict:
    """Pure transform: adzump session.context dict → ds campaign_data dict."""
    from utils.helpers import get_today_end_date_with_duration

    product = context.get("product_data") or {}
    spec = context.get("campaign_spec") or {}
    competitive = context.get("competitor_analysis") or {}
    location_meta = context.get("_location_meta") or {}
    account_names = context.get("account_names") or {}

    duration_days = _extract_int(spec.get("duration"))
    summary = product.get("summary") or ""

    # Compute startDate/endDate from durationDays — ds chat normally seeds
    # these at confirmation time (helpers.get_today_end_date_with_duration);
    # adzump skips that step so we do it here.
    dates = get_today_end_date_with_duration(duration_days) if duration_days else {}

    return {
        # Core CampaignData fields (typed in models/campaign_data_model.py)
        "businessName": product.get("product_name") or "",
        "websiteURL": _resolve_url(context),
        "budget": str(_extract_int(spec.get("budget")) or "") or None,
        "durationDays": duration_days,
        "startDate": dates.get("startDate"),
        "endDate": dates.get("endDate"),
        "loginCustomerId": _strip_account_id(spec.get("parent_account")),
        "customerId": _strip_account_id(spec.get("account")),

        # Extras consumed by other ds services (chat / external_link / ...)
        "platform": spec.get("platform"),
        "locations": _resolve_locations(context),
        "productSummary": summary,
        # ds keyword/creative services read `business_summary` (snake_case)
        "business_summary": summary,
        "businessType": product.get("business_type") or "",
        "competitors": competitive.get("competitors") or [],
        "accountNames": account_names,

        # Meta-only — passed through by name; ds Meta path reads as needed
        "fbPageId": _strip_account_id(spec.get("fb_page")),
        "igAccountId": _strip_account_id(spec.get("ig_page")),

        # Provenance — useful for debugging / re-syncing
        "adzumpProductId": context.get("product_id"),
        "adzumpSessionId": context.get("_adzump_session_id_seed", ""),
        "adzumpLocationLat": location_meta.get("lat"),
        "adzumpLocationLng": location_meta.get("lng"),
    }


# ── ds session creation ──────────────────────────────────────────────────


def _create_ds_session(campaign_data: dict, client_code: str) -> str:
    """Create a ds session in the in-memory `sessions` dict and return its id.

    Mirrors the shape `chat_service.start_session()` writes so that
    downstream services (chat_service / google_keywords_service /
    create_campaign_service / ads_service) all read what they expect.
    """
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "chat_history": [],
        "last_activity": datetime.now(timezone.utc),
        "campaign_data": campaign_data,
        # adzump already collected and confirmed everything — mark complete so
        # `get_basic_details` returns the actual `campaign_data` dict (the
        # in-progress branch returns presence booleans only, which broke
        # downstream ads/keywords UIs that read real values).
        "status": "completed",
        "mcc_options": [],
        "customer_options": [],
        "client_code": client_code,
    }
    logger.info("adzump_bridge_session_created",
                session_id=session_id, client_code=client_code,
                businessName=campaign_data.get("businessName"))
    return session_id


# ── Public entry point ────────────────────────────────────────────────────


async def create_session_from_adzump(adzump_session_id: str) -> dict:
    """Pull the adzump session, map it, create a ds session.

    Reads auth from the request-scoped `auth_context` ContextVar (set by ds's
    middleware on incoming requests). Returns
    ``{"session_id": "...", "campaign_data": {...}, "source_adzump_session_id": "..."}``.
    """
    if not adzump_session_id:
        raise BusinessValidationException("adzump_session_id is required")

    access_token = auth_context.access_token
    client_code = auth_context.client_code
    if not access_token or not client_code:
        raise BusinessValidationException(
            "Missing auth context (access_token / client_code). "
            "Caller must include Authorization + clientCode headers.",
        )

    payload = await _fetch_adzump_session(
        adzump_session_id,
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=auth_context.x_forwarded_host,
        x_forwarded_port=auth_context.x_forwarded_port,
    )

    raw_session = payload.get("session") or {}
    context_json = raw_session.get("context_json") or "{}"
    try:
        context = json.loads(context_json) if isinstance(context_json, str) else (context_json or {})
    except (ValueError, json.JSONDecodeError) as e:
        raise BusinessValidationException(
            f"Adzump session context_json is not valid JSON: {e}",
        ) from e

    # Stash the source id in context before mapping so it lands in
    # campaign_data.adzumpSessionId for traceability.
    context["_adzump_session_id_seed"] = adzump_session_id

    campaign_data = map_adzump_context_to_campaign_data(context)
    ds_session_id = _create_ds_session(campaign_data, client_code)

    return {
        "session_id": ds_session_id,
        "campaign_data": campaign_data,
        "source_adzump_session_id": adzump_session_id,
    }
