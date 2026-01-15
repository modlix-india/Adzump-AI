import asyncio
from fastapi import APIRouter, HTTPException, Header
from models.assets_models.assets_request_model import AssetRequest
from models.assets_models.assets_response_model import AssetResponse
from services.assets.call_assets_service import CallAssetsService
from services.assets.call_out_service import CalloutsService
from services.assets.site_link_service import SitelinksService
from services.assets.structured_snippet_service import StructuredSnippetsService
from services.assets.whatsapp_asset_service import WhatsAppAssetsService


router = APIRouter(prefix="/api/ds/ads/assets", tags=["Assets"])

ASSET_SERVICE_MAP = {
    "CALLOUTS": CalloutsService.generate,
    "SITE_LINKS": SitelinksService.generate,
    "STRUCTURED_SNIPPETS": StructuredSnippetsService.generate,
    "CALL_ASSETS": CallAssetsService.generate,
    "WHATSAPP_ASSETS": WhatsAppAssetsService.generate,
}


@router.post("/generate", response_model=AssetResponse)
async def generate_asset(
    request: AssetRequest,
    access_token: str = Header(...),
    clientCode: str = Header(...),
    x_forwarded_host: str = Header(..., alias="x-forwarded-host"),
    x_forwarded_port: str = Header(..., alias="x-forwarded-port"),
):
    results = {}
    invalid_assets = [a for a in request.asset_type if a not in ASSET_SERVICE_MAP]
    if invalid_assets:
        raise HTTPException(
            status_code=400, detail=f"Invalid asset types: {', '.join(invalid_assets)}"
        )
    try:
        tasks = [
            ASSET_SERVICE_MAP[asset](
                request.data_object_id,
                access_token,
                clientCode,
                x_forwarded_host,
                x_forwarded_port,
            )
            for asset in request.asset_type
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for asset, response in zip(request.asset_type, responses):
            if isinstance(response, Exception):
                results[asset] = {"success": False, "error": str(response)}
            else:
                results[asset] = {"success": True, "result": response}

        return AssetResponse(success=True, result=results)

    except Exception as e:
        return AssetResponse(success=False, result=None, error=str(e))
