from fastapi import APIRouter, Query

from adapters.meta.models.campaign_model import CreateCampaignRequest
from agents.meta import meta_campaign_agent
from utils.response_helpers import success_response
from agents.meta.adset_agent import meta_adset_agent
from adapters.meta.models.adset_model import CreateAdSetRequest

import json

from agents.meta.detailed_targeting_agent import meta_detailed_targeting_agent


router = APIRouter(prefix="/api/ds/ads/meta", tags=["meta-ads"])


@router.post("/campaign/generate")
async def generate_campaign(session_id: str = Query(..., alias="sessionId")):
    result = await meta_campaign_agent.create_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


# @router.post("/campaign/create")
# async def create_campaign(create_campaign_request: CreateCampaignRequest):
#     result = await meta_campaign_agent.create_campaign(create_campaign_request)
#     return success_response(data=result.model_dump(mode="json"))


@router.post("/adset/generate")
async def generate_adset(
    data_object_id: str = Query(..., alias="dataObjectId"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    result = await meta_adset_agent.create_payload(
        data_object_id=data_object_id,
        ad_account_id=ad_account_id,
    )

    return success_response(data=result)


# @router.post("/adset/create")
# async def create_adset(create_adset_request: CreateAdSetRequest):
#     result = await meta_adset_agent.create_adset(create_adset_request)
#     return success_response(data=result.model_dump(mode="json"))



@router.post("/adset/detailed-targeting/generate")
async def generate_detailed_targeting(
    session_id: str = Query(..., alias="sessionId"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    result = await meta_detailed_targeting_agent.create_payload(
        session_id=session_id,
        ad_account_id=ad_account_id,
    )

    return success_response(data=result)




