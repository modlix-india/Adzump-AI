from fastapi import APIRouter, Query

from adapters.meta.models import CreateCampaignRequest
from agents.meta import meta_campaign_agent
from utils.response_helpers import success_response
from adapters.meta.models import CreateCreativeRequest
from agents.meta.creative_agent import meta_creative_agent
from services.session_manager import sessions
from exceptions.custom_exceptions import BusinessValidationException


router = APIRouter(prefix="/api/ds/ads/meta", tags=["meta-ads"])


@router.post("/campaign/generate")
async def generate_campaign(session_id: str = Query(..., alias="sessionId")):
    result = await meta_campaign_agent.create_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/campaign/create")
async def create_campaign(create_campaign_request: CreateCampaignRequest):
    result = await meta_campaign_agent.create_campaign(create_campaign_request)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/creative/generate")
async def generate_creative(
    session_id: str = Query(..., alias="sessionId"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    if session_id not in sessions:
        raise BusinessValidationException("Session not found")

    sessions[session_id].setdefault("campaign_data", {})
    sessions[session_id]["campaign_data"]["adAccountId"] = ad_account_id

    result = await meta_creative_agent.create_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/creative/image/generate")
async def generate_creative_image(session_id: str = Query(..., alias="sessionId")):
    result = await meta_creative_agent.generate_image(session_id)
    return success_response(data=result.model_dump(mode="json"))



# @router.post("/creative/create")
# async def create_creative(create_creative_request: CreateCreativeRequest):
#     result = await meta_creative_agent.create_creative(create_creative_request)
#     return success_response(data=result.model_dump(mode="json"))
