import os
import tempfile
from typing import List,Dict,Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import JSONResponse
import requests
from services.scraper_service import scrape_website
from services.search_term_pipeline import SearchTermPipeline
from services.summarise_external_links import summarize_with_context
from services.summary import make_readable
from services.ads_service import generate_ad_assets
from services.google_keywords_service import GoogleKeywordService
from services.pdf_service import process_pdf_from_path
from services.summary_service import merge_summaries
from services.google_ads_builder import build_google_ads_payloads
from services.banners import generate_banners
from services.optimize_ad import optimize_with_llm
from services.sitelink_service import generate_sitelinks_service
from services.budget_recommendation_service import generate_budget_recommendation_service

from models.keyword_model import (
    KeywordResearchRequest,
    OptimizedKeyword,
)



router = APIRouter(prefix="/api/ds/ads", tags=["ads"])

class BannerRequest(BaseModel):
    data: dict  

@router.post("/generate_banners")
async def create_banners(request: BannerRequest):
    try:
        banners = await generate_banners(request.data)
        return {"banners": banners}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/constructPayloads")
async def build_payloads(body: dict):
    try:
        ads = body.get("ads", {})
        customer_id = body.get("customerId", "")

        payloads = build_google_ads_payloads(customer_id, ads)
        return {"success": True, "payloads": payloads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build payloads: {e}")

class WebsiteAnalysisRequest(BaseModel):
    websiteUrl: str

@router.post("/scrape")
async def analyze_website(request: WebsiteAnalysisRequest):
    try:
        # Scrape website content asynchronously
        scraped_data = await scrape_website(request.websiteUrl)

        # Construct final response
        response = {
            "status": "success",
            "data": {
                "websiteUrl": request.websiteUrl,
                "scrapedData": scraped_data
            }
        }

        return JSONResponse(content=response)

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )
    

class ReadableRequest(BaseModel):
    scrapedData: dict

@router.post("/scrappedSummary")
async def make_readable_endpoint(req: ReadableRequest):
    try:
        result = await make_readable(req.scrapedData)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {
            "status": "success",
            "data": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

class AdAssetRequest(BaseModel):
    summary: str
    positive_keywords: List[Dict[str, Any]]

@router.post("/adAssets")
async def create_ad_assets(req: AdAssetRequest):
    try:
        result = await generate_ad_assets(req.summary, req.positive_keywords)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {
            "status": "success",
            "data": {
                "headlines": result.get("headlines", []),
                "descriptions": result.get("descriptions", []),
                "audience": {
                    "gender": result.get("audience", {}).get("gender", []),
                    "age_range": result.get("audience", {}).get("age_range", [])
                }
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
class SummariesRequest(BaseModel):
    summaries: List[str]

@router.post("/merge-summaries")
async def merge_summaries_endpoint(request: SummariesRequest):
    final_summary = merge_summaries(request.summaries)
    return {
        "success": True if request.summaries else False,
        "input_count": len(request.summaries),
        "final_summary": final_summary
    }
class SummarizeRequest(BaseModel):
    pdf_url: str

@router.post("/summarize-pdf")
async def summarize_pdf(request: SummarizeRequest):
    try:
        pdf_url = request.pdf_url
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

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

class SummaryRequest(BaseModel):
    scrapedData: dict
    context:str

@router.post("/externalSummary")
async def fetch_exteranl_summary(req: SummaryRequest):
    try:
        result = await summarize_with_context(req.scrapedData, req.context)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {
            "status": "success",
            "data": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

gks = GoogleKeywordService()

class GoogleKeywordsRequest(KeywordResearchRequest):
    """Inherits all the fields from KeywordResearchRequest"""
    pass

class GoogleNegativeRequest(BaseModel):
    data_object_id:str
    positive_keywords:List[OptimizedKeyword]

@router.post("/gks/positive")
async def gks_positive(
        google_keyword_request: GoogleKeywordsRequest,
        client_code: str = Header(..., alias="clientCode"),
        session_id: str = Header(..., alias="sessionId"),
        access_token:str = Header(...,alias="access-token")
):
    try:
        request_dict = google_keyword_request.model_dump()

        positives = await gks.extract_positive_strategy(
            customer_id=request_dict["customer_id"],
            client_code=client_code,
            session_id=session_id,
            access_token=access_token,
            keyword_type=request_dict["keyword_type"],
            data_object_id=request_dict["data_object_id"],
            location_ids=request_dict["location_ids"],
            language_id=request_dict["language_id"],
            seed_count=request_dict["seed_count"],
            target_positive_count=request_dict["target_positive_count"],
        )
        return {"status": "success", "data": positives}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/gks/negative")
async def gks_negative(google_keyword_request:GoogleNegativeRequest,
                    client_code:str = Header(...,alias="clientCode"),
                    access_token:str = Header(...,alias="access-token")
):
    try:
        negatives = await gks.extract_negative_strategy(
            client_code=client_code,
            access_token=access_token,
            positive_keywords=google_keyword_request.positive_keywords,
            data_object_id=google_keyword_request.data_object_id
        )
        return{
            "status":"success",
            "data":{
                "negative_keywords":negatives,
                "total_negatives":len(negatives)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))
class OptimizeCampaignRequest(BaseModel):
    campaignData: List[Dict]
    basicData: Dict

@router.post("/optimize-campaign")
async def optimize_campaign(req: OptimizeCampaignRequest):
    try:
        result = await optimize_with_llm({
            "campaignData": req.campaignData,
            "basicData": req.basicData
        })
        return {
            "status": "success",
            "optimizedData": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

class AnalyzeSearchTermRequest(BaseModel):
    client_code: str
    customer_id: str
    login_customer_id: str
    campaign_id: str
    duration: str  # e.g., "LAST_30_DAYS" or "01/01/2025,31/01/2025"


# ✅ New helper function to initialize the class
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

# ----- Router Endpoint For Generete Site Lins -----

class SitelinkRequest(BaseModel):
    data_object_id: str


@router.post("/generate-sitelinks")
async def create_sitelinks(
    request: SitelinkRequest,
    access_token: str = Header(..., alias="access-token"),
    client_code: str = Header(..., alias="clientCode"),
):
    """
    Generate high-quality, lead-focused Google Ads sitelinks.
    Only 'data_object_id' is passed in payload; 
    'access_token' and 'clientCode' come from headers.
    """
    try:
        sitelinks = await generate_sitelinks_service(
            data_object_id=request.data_object_id,
            access_token=access_token,
            client_code=client_code
        )
        return {"sitelinks": sitelinks}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
# -------------------- Budget Recommendation --------------------

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