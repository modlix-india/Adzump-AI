from fastapi import APIRouter, Query

from adapters.meta.models import CreateCampaignRequest
from agents.meta import meta_campaign_agent
from utils.response_helpers import success_response

router = APIRouter(prefix="/api/ds/ads/meta", tags=["meta-ads"])


@router.post("/campaign/generate")
async def generate_campaign(session_id: str = Query(..., alias="sessionId")):
    result = await meta_campaign_agent.create_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/campaign/create")
async def create_campaign(create_campaign_request: CreateCampaignRequest):
    result = await meta_campaign_agent.create_campaign(create_campaign_request)
    return success_response(data=result.model_dump(mode="json"))
