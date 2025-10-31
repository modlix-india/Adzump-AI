import os
import tempfile
import requests
from typing import List,Dict,Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Header, Body
from fastapi.responses import JSONResponse
from services.search_term_pipeline import SearchTermPipeline
from services.google_keywords_service import GoogleKeywordService
from services.scraper_service import scrape_website
from services.summary import make_readable
from services.ads_service import generate_ad_assets
from services.pdf_service import process_pdf_from_path
from services.google_ads_builder import build_google_ads_payloads
from services.budget_recommendation_service import generate_budget_recommendation_service
from utils.response_helpers import error_response, success_response


router = APIRouter(prefix="/api/ds/ads", tags=["ads"])

@router.post("/scrape")
async def analyze_website(websiteUrl: str = Body(..., embed=True),access_token: str = Header(..., alias="access-token"),
    client_code: str = Header(..., alias="clientCode"),):
    try:
        scraped_data = await scrape_website(websiteUrl,access_token=access_token,
            client_code=client_code)
        response = {
            "status": "success",
            "data": {
                "websiteUrl": websiteUrl,
                "scrapedData": scraped_data
            }
        }
        return success_response(response)
    except Exception as e:
        return error_response(str(e))


@router.post("/generate/summary")
async def make_readable_endpoint(scrapedData: dict = Body(..., embed=True)):
    try:
        result = await make_readable(scrapedData)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return success_response(result)
    except Exception as e:
        return error_response(str(e))


@router.post("/generate/pdf-summary")
async def summarize_pdf(pdf_url: str = Body(..., embed=True)):
    try:
        # Download PDF from given URL
        response = requests.get(pdf_url, stream=True)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not download PDF")
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tmp_file_path = tmp_file.name
        # Process PDF
        result = process_pdf_from_path(tmp_file_path, pdf_url)
        # Cleanup
        os.remove(tmp_file_path)
        return success_response(result)
    except Exception as e:
        return error_response(str(e))


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

class GoogleKeywordsRequest(BaseModel):
    scraped_data: str
    customer_id: str
    url: str = None
    location_ids: List[str] = []
    language_id: int = 1000
    seed_count: int = 40
    target_positive_count: int = 30

class GoogleNegativeRequest(BaseModel):
    scraped_data: str
    url: str = None
    positive_keywords: List[Dict[str, Any]]


@router.post("/gks/positive")
async def gks_positive(
        google_keyword_request: GoogleKeywordsRequest,
        client_code: str = Header(..., alias="clientCode"),
        session_id: str = Header(..., alias="sessionId")
):
    try:
        positives = gks.extract_positive_strategy(
            scraped_data=google_keyword_request.scraped_data,
            customer_id=google_keyword_request.customer_id,
            client_code=client_code,
            session_id=session_id,
            location_ids=google_keyword_request.location_ids,
            url=google_keyword_request.url,
            language_id=google_keyword_request.language_id,
            seed_count=google_keyword_request.seed_count,
            target_positive_count=google_keyword_request.target_positive_count,
        )
        return {"status": "success", "positive_keywords": positives}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/gks/negative")
async def gks_negative(google_keyword_request: GoogleNegativeRequest, ):
    try:
        negatives = gks.generate_negative_keywords(
            optimized_positive_keywords=google_keyword_request.positive_keywords,
            scraped_data=google_keyword_request.scraped_data,
            url=google_keyword_request.url
        )
        return {"status": "success", "negative_keywords": negatives}
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