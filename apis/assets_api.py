from fastapi import APIRouter, HTTPException,Header
from models.assets_models.request_models import AssetRequest
from models.assets_models.response_models import AssetResponse
from services.assets.call_assets_service import CallAssetsService
from services.assets.call_out_service import CalloutsService
from services.assets.site_link_service import SitelinksService
from services.assets.structured_snippet_service import StructuredSnippetsService

router = APIRouter(prefix="/api/ds/ads/assets", tags=["Assets"])

ASSET_SERVICE_MAP = {
    "callouts": CalloutsService.generate,
    "sitelinks": SitelinksService.generate,
    "structured_snippets": StructuredSnippetsService.generate,
    "callassets":CallAssetsService.generate
}

@router.post("/generate", response_model=AssetResponse)
async def generate_asset(request: AssetRequest, access_token: str = Header(...),
    clientcode: str = Header(...)):
    service = ASSET_SERVICE_MAP.get(request.asset_type.lower())

    if not service:
        raise HTTPException(status_code=400, detail=f"Invalid asset_type '{request.asset_type}'")

    try:
        result = await service(request.data_object_id, access_token, clientcode)
        return AssetResponse(success=True, result=result)
    except Exception as e:
        return AssetResponse(success=False, result=None, error=str(e))
