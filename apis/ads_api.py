from typing import List,Dict,Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Header, Body
from fastapi.responses import JSONResponse
from services.search_term_pipeline import SearchTermPipeline
from services.google_keywords_service import GoogleKeywordService
from services.ads_service import generate_ad_assets
from services.google_ads_builder import build_google_ads_payloads
from services.budget_recommendation_service import generate_budget_recommendation_service

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


@router.post("/generate/payloads")
async def build_payloads(body: dict):
    try:
        ads = body.get("ads", {})
        customer_id = body.get("customerId", "")
        payloads = build_google_ads_payloads(customer_id, ads)
        return success_response(payloads)
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

class BudgetRequest(BaseModel):
    clientCode: str
    loginCustomerId: str
    customerId: str
    campaignId: str
    startDate: str
    endDate: str

@router.post("/generate_budget_recommendation")
async def generate_budget_recommendation(request: BudgetRequest):
    try:
        result = await generate_budget_recommendation_service(
            customer_id=request.customerId,
            login_customer_id=request.loginCustomerId,
            campaign_id=request.campaignId,
            start_date=request.startDate,
            end_date=request.endDate,
            client_code=request.clientCode
        )
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))