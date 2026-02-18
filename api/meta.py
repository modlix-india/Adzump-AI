from fastapi import APIRouter, Query

from agents.meta import meta_campaign_agent
from agents.meta.adset_agent import meta_adset_agent
from utils.response_helpers import success_response

router = APIRouter(prefix="/api/ds/ads/meta", tags=["meta-ads"])


@router.post("/campaign/generate")
async def generate_campaign(session_id: str = Query(..., alias="sessionId")):
    result = await meta_campaign_agent.generate_payload(session_id)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/adset/generate")
async def generate_adset(session_id: str = Query(..., alias="sessionId")):
    result = await meta_adset_agent.generate_payload(session_id)
    return success_response(data=result)


# @router.post("/adset/create")
# async def create_adset(create_adset_request: CreateAdSetRequest):
#     result = await meta_adset_agent.create_adset(create_adset_request)
#     return success_response(data=result.model_dump(mode="json"))



@router.post("/adset/detailed-targeting/generate")
async def generate_detailed_targeting(
    website_url: str = Query(..., alias="websiteUrl"),
    ad_account_id: str = Query(..., alias="adAccountId"),
):
    result = await meta_detailed_targeting_agent.create_payload(
        website_url=website_url,
        ad_account_id=ad_account_id,
    )

    return success_response(data=result)




