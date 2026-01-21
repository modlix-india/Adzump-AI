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


@router.post("/meta-adset/service")
async def generate_meta_adset(
    request: MetaAdSetRequest,
    authorization: str = Header(...),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(None),
    x_forwarded_port: str = Header(None),
):
    result = await MetaAdSetService.generate_adset(
        data_object_id=request.dataObjectId,
        access_token=authorization,
        client_code=client_code,
        goal=request.goal,
        region=request.region,
        ad_account_id=request.adAccountId,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    return {
        "status": "success",
        "data": result
    }

# Create Meta Ad-Set

@router.post("/meta-adset/create")
async def create_meta_adset(
    request: MetaAdSetRequest,
    meta_access_token: str = Header(..., alias="meta-access-token"),
):
    result = await MetaAdSetCreateService.create_adset(
        ad_account_id=request.adAccountId,
        access_token=meta_access_token,
        campaign_id=request.campaignId,
        adset_payload=request.adsetPayload
    )

    return {
        "status": "success",
        "data": {"adsetId": result.get("id")}
    }
