import os
import tempfile
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Body
from dependencies.header_dependencies import get_common_headers
from exceptions.custom_exceptions import BaseAppException
from models.business_model import AnalyzeRequest, AnalyzeResponse, CommonHeaders, ExternalSummaryRequest, ScreenshotRequest, ScreenshotResponse
from services.business_service import process_screenshot_flow, process_website_data
from services.external_link_summary_service import process_external_link
from services.pdf_service import process_pdf_from_path
from utils.response_helpers import error_response, success_response

router = APIRouter(prefix="/api/ds/business", tags=["business"])
logger = logging.getLogger(__name__)



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


@router.post("/websiteSummary")
async def analyze_website(
    payload: AnalyzeRequest = Body(...),
    headers: CommonHeaders = Depends(get_common_headers)
):
    try:
        result = await process_website_data(
            website_url=payload.business_url,
            rescrape=payload.rescrape,
            access_token=headers.access_token,
            client_code=headers.client_code,
            x_forwarded_host=headers.x_forwarded_host,
            x_forwarded_port=headers.x_forwarded_port,
        )

        response = AnalyzeResponse(
            storage_id=result.get("storageId"),
            business_url=result.get("websiteUrl"),
            business_type=result.get("businessType"),
            summary=result.get("summary"),
            final_summary=result.get("finalSummary"),
        )
        return success_response(response.model_dump())
    except BaseAppException as e:
        return error_response(e.message, e.status_code)
    except Exception as e:
        logger.exception(f"[AnalyzeController] Unexpected error: {e}")
        return error_response("Unexpected error while analyzing website")



@router.post("/screenshot")
async def take_screenshot(
    payload: ScreenshotRequest = Body(...),
    headers: CommonHeaders = Depends(get_common_headers),
):
    try:
        result = await process_screenshot_flow(
            business_url=payload.business_url,
            external_url=payload.external_url,
            retake=payload.retake,
            client_code=headers.client_code,
            access_token=headers.access_token,
            x_forwarded_host=headers.x_forwarded_host,
            x_forwarded_port=headers.x_forwarded_port,
        )
        response = ScreenshotResponse(
            business_url=result.get("businessUrl"),
            external_url=result.get("externalUrl"),
            retake=payload.retake,
            storage_id=result.get("storageId"),
            business_screenshot_url=result.get("businessScreenshotUrl"),
            external_screenshot_url=result.get("externalScreenshotUrl"),
        )
        return success_response(response.model_dump(by_alias=True))
    except BaseAppException as e:
        return error_response(e.message, status_code=e.status_code)
    except Exception as e:
        logger.exception(f"[ScreenshotController] Unexpected error: {e}")
        return error_response("Unexpected error while processing screenshot")


@router.post("/generate/external-summary")
async def generate_external_summary(
    payload: ExternalSummaryRequest = Body(...),
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
        return success_response(result)
    except BaseAppException as e:
        return error_response(e.message, e.status_code)
    except Exception as e:
        logger.exception(f"[ExternalSummaryController] Unexpected error: {e}")
        return error_response("Unexpected error while generating external summary")