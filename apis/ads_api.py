from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Header, status, Body, Query
from services.search_term_pipeline import SearchTermPipeline
from services.google_keywords_service import GoogleKeywordService
from services.ads_service import generate_ad_assets
from services.budget_recommendation_service import generate_budget_recommendations
from services.create_campaign_service import CampaignServiceError
from models.keyword_model import KeywordResearchRequest, GoogleNegativeKwReq
from utils.response_helpers import error_response, success_response
from models.search_campaign_data_model import GenerateCampaignRequest
from services import create_campaign_service, chat_service
# TODO: Remove age optimization import - replaced by api/optimization.py
from services.age_optimization_service import generate_age_optimizations



router = APIRouter(prefix="/api/ds/ads", tags=["ads"])


@router.post("/generate/ad-assets")
async def create_ad_assets(
    summary: str = Body(...), positive_keywords: List[Dict[str, Any]] = Body(...)
):
    try:
        result = await generate_ad_assets(summary, positive_keywords)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        result = {
            "headlines": result.get("headlines", []),
            "descriptions": result.get("descriptions", []),
            "audience": {
                "gender": result.get("audience", {}).get("gender", []),
                "age_range": result.get("audience", {}).get("age_range", []),
            },
        }
        return success_response(result)
    except Exception as e:
        return error_response(str(e))


gks = GoogleKeywordService()


@router.post("/gks/positive")
async def gks_positive(
    google_keyword_request: KeywordResearchRequest,
    client_code: str = Header(..., alias="clientCode"),
    session_id: str = Header(..., alias="sessionId"),
    access_token: str = Header(..., alias="access-token"),
    x_forwarded_host: str = Header(..., alias="x-forwarded-host"),
    x_forwarded_port: str = Header(..., alias="x-forwarded-port"),
):
    try:
        positives = await gks.extract_positive_strategy(
            keyword_request=google_keyword_request,
            client_code=client_code,
            session_id=session_id,
            access_token=access_token,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        return {"status": "success", "data": positives}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gks/negative")
async def gks_negative(
    google_keyword_request: GoogleNegativeKwReq,
    client_code: str = Header(..., alias="clientCode"),
    access_token: str = Header(..., alias="access-token"),
    x_forwarded_host: str = Header(..., alias="x-forwarded-host"),
    x_forwarded_port: str = Header(..., alias="x-forwarded-port"),
):
    try:
        negatives = await gks.extract_negative_strategy(
            keyword_request=google_keyword_request,
            client_code=client_code,
            access_token=access_token,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        return {
            "status": "success",
            "data": {"negative_keywords": negatives, "total_negatives": len(negatives)},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/budget")
async def generate_budget_recommendation(
    clientCode: str = Header(...),
    loginCustomerId: str = Header(...),
    customerId: str = Header(...),
    campaignId: str = Query(...),
):
    try:
        result = await generate_budget_recommendations(
            customer_id=customerId,
            login_customer_id=loginCustomerId,
            campaign_id=campaignId,
            client_code=clientCode,
        )
        return {"status": "success", "data": result}

    except CampaignServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-campaign")
async def generate_campaign(
    request: GenerateCampaignRequest,
    clientCode: str = Header(..., alias="clientCode"),
):
    """
    Router endpoint:
    - Accepts GenerateCampaignRequest body
    - Requires clientCode header
    - Delegates work to campaign service
    """
    try:
        # Call service to create payload and post to Google Ads
        result = await create_campaign_service.create_and_post_campaign(
            request_body=request, client_code=clientCode
        )

        return {"status": "success", "data": result}

    except CampaignServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/search_term")
async def analyze_search_terms_route(
    access_token: str = Header(..., alias="accessToken"),
    customer_id: str = Header(..., alias="customerId"),
    login_customer_id: str = Header(..., alias="loginCustomerId"),
    client_code: str = Header(..., alias="clientCode"),
    campaign_id: str = Query(..., alias="campaignId"),
    duration: str = Query(...),
):
    try:
        pipeline = SearchTermPipeline(
            client_code=client_code,
            customer_id=customer_id,
            login_customer_id=login_customer_id,
            campaign_id=campaign_id,
            duration=duration,
            access_token=access_token,
        )

        results = await pipeline.run_pipeline()

        return {"status": "success", "data": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-basic-details/{session_id}")
async def get_session(session_id: str):
    return await chat_service.get_basic_details(session_id)


@router.post("/optimize/age")
async def generate_age_optimization(
    clientCode: str = Header(...),
    loginCustomerId: str = Header(...),
    customerId: str = Header(...),
    campaignId: str = Query(...),
    duration: str = Query(...),
):
    try:
        result = await generate_age_optimizations(
            customer_id=customerId,
            login_customer_id=loginCustomerId,
            campaign_id=campaignId,
            client_code=clientCode,
            duration=duration,
        )
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))