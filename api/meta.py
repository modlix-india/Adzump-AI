from fastapi import APIRouter, Query

from agents.meta import meta_campaign_agent
from agents.meta.adset_agent import meta_adset_agent
from utils.response_helpers import success_response, error_response
from agents.meta.creative_agent import meta_creative_agent
from core.models.meta import CreateMetaAdRequest


from adapters.meta.client import meta_client
from adapters.meta.ad_creation_orchestrator import MetaAdCreationOrchestrator
from adapters.meta.exceptions import MetaAdCreationError

router = APIRouter(prefix="/api/ds/ads/meta", tags=["meta-ads"])


@router.post("/campaign/generate")
async def generate_campaign(session_id: str = Query(..., alias="sessionId")):
    result = await meta_campaign_agent.generate_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/adset/generate")
async def generate_adset(
    session_id: str = Query(..., alias="sessionId"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    result = await meta_adset_agent.generate_payload(session_id, ad_account_id)
    return success_response(data=result)


@router.post("/creative/generate")
async def generate_creative(session_id: str = Query(..., alias="sessionId")):
    result = await meta_creative_agent.generate_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/creative/image/generate")
async def generate_creative_image(
    session_id: str = Query(..., alias="sessionId"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    result = await meta_creative_agent.generate_image(session_id, ad_account_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/create-ad")
async def create_meta_ads(
    payload: CreateMetaAdRequest,
    inspect_payload: bool = Query(default=False, alias="inspect_payload"),
):
    """
    This endpoint is need client_code in header it will be used to fetch meta api token from auth_context
    """
    ad_account_id = payload.account.ad_account_id

    orchestrator = MetaAdCreationOrchestrator(meta_client, ad_account_id)

    try:
        result = await orchestrator.create_full_structure(payload, inspect_payload)
        return success_response(data=result)
    except MetaAdCreationError as e:
        status_code = getattr(e.original_exc, "status_code", 400)
        message = getattr(e.original_exc, "message", str(e.original_exc))
        meta_error = getattr(e.original_exc, "error_data", {}).get("error", {})

        return error_response(
            message=message,
            status_code=status_code,
            details={
                "failed_stage": e.failed_stage,
                "meta_error": meta_error,
                "ids": e.existing_ids,
            },
        )
