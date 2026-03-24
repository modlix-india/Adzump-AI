from fastapi import APIRouter, Query

from agents.meta import meta_campaign_agent
from agents.meta.adset_agent import meta_adset_agent
from utils.response_helpers import success_response
from core.models.meta import CreateCreativeRequest
from core.models.lead_form import LeadFormPayload
from agents.meta.creative_agent import meta_creative_agent
from agents.meta.lead_form_agent import meta_lead_form_agent



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
    ad_account_id: str = Query(..., alias="adAccountId")
):
    result = await meta_creative_agent.generate_image(session_id, ad_account_id)
    return success_response(data=result.model_dump(mode="json"))    


@router.post("/lead-form/generate")
async def generate_lead_form(session_id: str = Query(..., alias="sessionId")):
    result = await meta_lead_form_agent.generate_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/lead-form/create")
async def create_lead_form(
    payload: LeadFormPayload,
    session_id: str = Query(..., alias="sessionId")
):
    result = await meta_lead_form_agent.create_lead_form(session_id, payload)
    return success_response(data=result)