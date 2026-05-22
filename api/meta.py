from fastapi import APIRouter, Query
from agents.meta import meta_campaign_agent
from agents.meta.adset_agent import meta_adset_agent
from utils.response_helpers import success_response
from core.models.lead_form import LeadFormPayload
from agents.meta.creative_agent import meta_creative_agent
from core.models.meta import (
    MetaAdCreationRequest,
    PlacementRequest,
    CreativeGenerationRequest,
    CreativeType,
)
from agents.meta.lead_form_agent import meta_lead_form_agent
from adapters.meta.ad_creation_orchestrator import MetaAdCreationOrchestrator
from agents.meta.detailed_targeting_agent import detailed_targeting_agent
from agents.meta.ads_placement_agent import meta_ads_placement_agent


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
    return success_response(data=result.model_dump(mode="json"))


@router.post("/creative/generate")
async def generate_creative(
    body: CreativeGenerationRequest, session_id: str = Query(..., alias="sessionId")
):
    if body.creative_type == CreativeType.CAROUSEL:
        result = await meta_creative_agent.generate_carousel_payload(
            session_id=session_id,
            card_count=body.card_count or 5,
        )
    else:
        result = await meta_creative_agent.generate_payload(
            session_id=session_id, destination_type=body.destination_type
        )
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
    payload: MetaAdCreationRequest,
    inspect_payload: bool = Query(default=False, alias="inspect_payload"),
):
    """
    Creates a full Meta ad structure (campaign → ad set → ad).
    Requires 'ClientCode' header for authentication context.
    """
    result = await MetaAdCreationOrchestrator.create_full_structure(
        payload, inspect_payload
    )
    return success_response(data=result.model_dump(mode="json"))


@router.post("/lead-form/generate")
async def generate_lead_form(session_id: str = Query(..., alias="sessionId")):
    """timezone`: Optional time zone string (e.g., 'Asia/Kolkata'). By default 'Asia/Kolkata' is used."""
    result = await meta_lead_form_agent.generate_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/lead-form/create")
async def create_lead_form(
    payload: LeadFormPayload, session_id: str = Query(..., alias="sessionId")
):
    result = await meta_lead_form_agent.create_lead_form(session_id, payload)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/targeting-suggestions")
async def generate_meta_targeting_suggestions(
    session_id: str = Query(
        ..., alias="sessionId", min_length=1, description="The session ID"
    ),
    ad_account_id: str = Query(
        ...,
        alias="adAccountId",
        min_length=1,
        description="The Meta Ad Account ID (with or without 'act_' prefix)",
    ),
):
    """
    Generate Meta targeting suggestions for interests, demographics, and behaviors.
    """
    result = await detailed_targeting_agent.generate_detailed_targeting_suggestions(
        session_id=session_id,
        ad_account_id=ad_account_id,
    )
    return success_response(data=result.model_dump(mode="json"))


@router.post("/placement/generate")
async def generate_placements(
    body: PlacementRequest,
    session_id: str = Query(..., alias="sessionId"),
):
    result = await meta_ads_placement_agent.generate_placements(
        session_id=session_id,
        objective=body.objective,
        creative_type=body.creative_type,
    )
    return success_response(data=result.model_dump(mode="json"))
