import os
import tempfile
from typing import Any, Dict, List
from pydantic import BaseModel
from fastapi import APIRouter,HTTPException
from fastapi.responses import JSONResponse
import requests
from services.scraper_service import scrape_website
from services.summarise_external_links import summarize_with_context
from services.summary import make_readable
from services.ads_service import generate_ad_assets
from services import keyword_planner, keyword_service
from services.pdf_service import process_pdf_from_path
from services.summary_service import merge_summaries
from services.google_ads_builder import build_google_ads_payloads
from services.banners import generate_banners

router = APIRouter()


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

@router.post("/adAssets")
async def create_ad_assets(req: AdAssetRequest):
    try:
        result = await generate_ad_assets(req.summary)

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
    

agent = keyword_service.StreamlinedKeywordAgent()
    

class KeywordRequest(BaseModel):
    scraped_data: str
    customer_id: str
    url: str 


@router.post("/keywords")
async def generate_keywords(req: KeywordRequest):
    try:
        result = agent.run_full_pipeline(
            scraped_data=req.scraped_data,
            customer_id=req.customer_id,
            url=req.url
        )

        return {
            "status": "success",
            "data": result
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
    

# positive keywords endPoint
keywordAgent = keyword_planner.AIKeywordAgent()
class PositiveKeywordRequest(BaseModel):
    scraped_data: str
    customer_id: str
    url: str = None
    seed_count: int = 40
    target_count: int = 50

@router.post("/positiveKeywords")
async def generate_positive_keywords(req: PositiveKeywordRequest):
    try:
        result = keywordAgent.run_positive_pipeline(
            scraped_data =req.scraped_data,
            url=req.url,
            customer_id =req.customer_id
        )
        return {
            "status":"Success",
            "data":result
        }
    except Exception as e:
        raise HTTPException(status_code=500,details=str(e))
    
# negative keyword endPoint
class NegativeKeywordRequest(BaseModel):
    scraped_data:str
    url:str=None
    positive_keywords:List[Dict[str,Any]]

@router.post("/negativeKeywords")
async def generateNegativeKeywords(req:NegativeKeywordRequest):
    try:
        result = keywordAgent.run_negative_pipeline(
            scraped_data= req.scraped_data,
            url=req.url,
            optimized_positive_keywords=req.positive_keywords
        )
        return{
            "status":"Success",
            "data":result
        }
    except Exception as e:
        raise HTTPException(status_code=500,details=str(e))
    
# Endpoint for the full(positive and negative) keywords generation
# used the above keywordRequest class
@router.post("/keywordSuggestions")
async def generateKeywordSuggestions(req:KeywordRequest):
    try:
        result = keywordAgent.run_keywords_pipeline(
            scraped_data=req.scraped_data,
            url=req.url,
            customer_id=req.customer_id
        )
        return {
            "status":"Success",
            "data":result
        }
    except Exception as e:
        raise HTTPException(status_code=500,details=str(e))