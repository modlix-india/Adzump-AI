import os
import tempfile
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Body
from dependencies.header_dependencies import CommonHeaders, get_common_headers
from exceptions.custom_exceptions import BaseAppException
from models.business_model import  ScreenshotRequest, WebsiteSummaryRequest
from services.business_service import BusinessService
from services.external_link_summary_service import process_external_link
from services.pdf_service import process_pdf_from_path
from services.screenshot_service import ScreenshotService
from services.final_summary_service import generate_final_summary
from utils.response_helpers import error_response, success_response

router = APIRouter(prefix="/api/ds/business", tags=["business"])
logger = logging.getLogger(__name__)


@router.post("/screenshot")
async def take_screenshot(
    payload: ScreenshotRequest = Body(...),
    headers: CommonHeaders = Depends(get_common_headers),
):
    try:
        service = ScreenshotService(
            access_token=headers.access_token,
            client_code=headers.client_code,
            xh=headers.x_forwarded_host,
            xp=headers.x_forwarded_port,
        )
        target_url = payload.external_url or payload.business_url
        result = await service.process(
            business_url=payload.business_url,
            url=target_url,
            retake=payload.retake,
        )
        return success_response(result.model_dump())
    except BaseAppException as e:
        return error_response(e.message, status_code=e.status_code)
    except Exception as e:
        return error_response(f"Unexpected error: {e}")

@router.post("/websiteSummary")
async def analyze_website(
    payload: WebsiteSummaryRequest = Body(...),
    headers: CommonHeaders = Depends(get_common_headers)
):
    try:
        service = BusinessService()
        result = await service.process_website_data(
            website_url=payload.business_url,
            rescrape=payload.rescrape,
            access_token=headers.access_token,
            client_code=headers.client_code,
            x_forwarded_host=headers.x_forwarded_host,
            x_forwarded_port=headers.x_forwarded_port,
        )
        return success_response(result.model_dump())
    except BaseAppException as e:
        return error_response(e.message, e.status_code)
    except Exception as e:
        logger.exception(f"[AnalyzeController] Unexpected error: {e}")
        return error_response("Unexpected error while analyzing website")


@router.post("/generate/external-summary")
async def generate_external_summary(
    payload: WebsiteSummaryRequest = Body(...),
    headers: CommonHeaders = Depends(get_common_headers)
):
    try:
        result = await process_external_link(
            external_url=payload.external_url,
            business_url=payload.business_url,
            rescrape=payload.rescrape,
            access_token=headers.access_token,
            client_code=headers.client_code,
            x_forwarded_host=headers.x_forwarded_host,
            x_forwarded_port=headers.x_forwarded_port,
        )
        return success_response(result.model_dump())
    except BaseAppException as e:
        return error_response(e.message, e.status_code)
    except Exception as e:
        logger.exception(f"[ExternalSummaryController] Unexpected error: {e}")
        return error_response("Unexpected error while generating external summary")

@router.post("/generate/pdf-summary")
async def summarize_pdf(
    pdf_url: str = Body(..., embed=True),
    business_url: str = Body(..., embed=True),
    access_token: str = Header(..., alias="access-token"),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(alias="x-forwarded-host", default=None),
    x_forwarded_port: str = Header(alias="x-forwarded-port", default=None),
):
    try:
        # 1. Download PDF using async
        async with httpx.AsyncClient() as client:
            response = await client.get(pdf_url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Could not download PDF")
        # 2. Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(response.content)
            file_path = tmp.name
        # 3. Process PDF (async)
        result = await process_pdf_from_path(
            file_path=file_path,
            source_url=pdf_url,
            business_url=business_url,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port,
        )
        # 4. Cleanup temp file
        os.remove(file_path)
        return success_response(result)
    except Exception as e:
        return error_response(str(e))

@router.post("/generate/final-summary")
async def generate_final_summary_endpoint(
    business_url: str = Body(..., embed=True),
    headers: CommonHeaders = Depends(get_common_headers)
):
    try:
        result = await generate_final_summary(
            business_url=business_url,
            access_token=headers.access_token,
            client_code=headers.client_code,
            x_forwarded_host=headers.x_forwarded_host,
            x_forwarded_port=headers.x_forwarded_port,
        )
        return success_response(result)
    except BaseAppException as e:
        return error_response(e.message, e.status_code)
    except Exception as e:
        logger.exception(f"[FinalSummaryController] Unexpected error: {e}")
        return error_response("Unexpected error while generating final summary")