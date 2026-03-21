from fastapi import APIRouter, Query ,Header, HTTPException, Body

from agents.meta import meta_campaign_agent
from agents.meta.adset_agent import meta_adset_agent
from utils.response_helpers import success_response
from agents.meta.creative_agent import meta_creative_agent



from adapters.meta.client import MetaClient
from adapters.meta.ad_creation_orchestrator import MetaAdCreationOrchestrator

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

@router.post("/create-ad")
async def create_meta_ads(
    payload: dict,
    client_code: str = Header(..., alias="ClientCode"),
    inspect_payload: str = Header(default="false", alias="InspectPayload")
):
    meta_client = MetaClient()
    ad_account_id = payload["account"]["ad_account_id"]
    inspect_payload = inspect_payload == "true"

    orchestrator = MetaAdCreationOrchestrator(
        meta_client,
        ad_account_id,
        client_code

    )

    result = await orchestrator.create_full_structure(payload, inspect_payload)

    return result
