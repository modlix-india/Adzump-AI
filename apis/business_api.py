
import os
import tempfile
import requests
from fastapi import APIRouter, HTTPException, Header, Body
from services.pdf_service import process_pdf_from_path
from services.scraper_service import scrape_website
from services.summary import make_readable
from utils.response_helpers import error_response, success_response

router = APIRouter(prefix="/api/ds/business", tags=["business"])

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