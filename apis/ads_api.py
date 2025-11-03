from typing import List,Dict,Any,Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Header,status, Body, Query
from fastapi.responses import JSONResponse
from services.search_term_pipeline import SearchTermPipeline
from services.google_keywords_service import GoogleKeywordService
from services.ads_service import generate_ad_assets
# from services.google_ads_builder import build_google_ads_payloads
from services.budget_recommendation_service import generate_budget_recommendations
from services.create_campaign_service import create_and_post_campaign, CampaignServiceError
from models.keyword_model import (
    KeywordResearchRequest,
    GoogleNegativeKwReq
)
from utils.response_helpers import error_response, success_response


router = APIRouter(prefix="/api/ds/ads", tags=["ads"])

@router.post("/generate/ad-assets")
async def create_ad_assets(summary: str = Body(...),positive_keywords: List[Dict[str, Any]] = Body(...)):
    try:
        result = await generate_ad_assets(summary, positive_keywords)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        result={
            "headlines": result.get("headlines", []),
            "descriptions": result.get("descriptions", []),
            "audience": {
                "gender": result.get("audience", {}).get("gender", []),
                "age_range": result.get("audience", {}).get("age_range", [])
                }
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
        access_token:str = Header(...,alias="access-token")
):
    try:
        positives = await gks.extract_positive_strategy(
            keyword_request=google_keyword_request,
            client_code=client_code,
            session_id=session_id,
            access_token=access_token,
        )
        return {"status": "success", "data": positives}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/gks/negative")
async def gks_negative(google_keyword_request: GoogleNegativeKwReq,
                    client_code:str = Header(...,alias="clientCode"),
                    access_token:str = Header(...,alias="access-token")
):
    try:
        negatives = await gks.extract_negative_strategy(
            keyword_request=google_keyword_request,
            client_code=client_code,
            access_token=access_token,
        )
        return{
            "status":"success",
            "data":{
                "negative_keywords":negatives,
                "total_negatives":len(negatives)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

class AnalyzeSearchTermRequest(BaseModel):
    client_code: str
    customer_id: str
    login_customer_id: str
    campaign_id: str
    duration: str


def start_search_term_pipeline(request: AnalyzeSearchTermRequest):
    return SearchTermPipeline(
        client_code=request.client_code,
        customer_id=request.customer_id,
        login_customer_id=request.login_customer_id,
        campaign_id=request.campaign_id,
        duration=request.duration,
    )

@router.post("/search_term")
async def analyze_search_terms_route(request: AnalyzeSearchTermRequest):
    """Endpoint to analyze search terms and classify them as positive or negative."""
    try:
        pipeline = start_search_term_pipeline(request)
        results = await pipeline.run_pipeline()
        return JSONResponse(
            content={"status": "success", "data": results},
            status_code=200
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    
@router.post("/optimize/budget")
async def generate_budget_recommendation(
    clientCode: str = Header(...),
    loginCustomerId: str = Header(...),
    customerId: str = Header(...),
    campaignId: str = Query(...)
):
    try:
        result = await generate_budget_recommendations(
            customer_id=customerId,
            login_customer_id=loginCustomerId,
            campaign_id=campaignId,
            client_code=clientCode
        )
        return {"status": "success", "data": result}

    except CampaignServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# ---------------- Pydantic Model ----------------
class GenerateCampaignRequest(BaseModel):
    customer_id: str
    loginCustomerId: str
    businessName: str
    budget: float
    startDate: str
    endDate: str
    goal: str
    websiteURL: str
    geoTargetTypeSetting: Dict[str, Any]
    locations: List[Dict[str, str]]
    targeting: List[Dict[str, Any]]
    # Assets optional, we will handle inside service if provided
    assets: Dict[str, Any] = None

# ------------------ Router ------------------
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
        # Convert Pydantic model to dict (preserves original keys)
        request_body = request.model_dump()

        # Call service to create payload and post to Google Ads
        result = await create_and_post_campaign(request_body=request_body, client_code=clientCode)

        return {"status": "success", "data": result}

    except CampaignServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # unexpected errors
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))