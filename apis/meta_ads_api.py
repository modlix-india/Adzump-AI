from fastapi import APIRouter, Header, HTTPException
from models.meta.meta_campaign_request import MetaCampaignRequest
from services.meta.meta_campaign_service import MetaCampaignService
from services.meta.meta_campaign_create_service import MetaCampaignCreateService
from models.meta.meta_adset_request import MetaAdSetRequest
from services.meta.meta_adset_service import MetaAdSetService
from services.meta.meta_adset_create_service import MetaAdSetCreateService
from models.meta.meta_ad_image_request import MetaAdImageRequest
from services.meta.meta_ad_image_service import MetaAdImageService
from services.meta.meta_ad_image_create_service import MetaAdImageCreateService
from models.meta.meta_creative_request import MetaCreativeRequest
from services.meta.meta_creative_pipeline import MetaCreativePipeline



router = APIRouter(
    prefix="/api/ds/ads",
    tags=["meta-ads"]
)

# Generate Meta Campaign

@router.post("/meta-campaign/service")
async def meta_campaign_service(
    request: MetaCampaignRequest,
    authorization: str = Header(...),
    x_forwarded_host: str = Header(None),
    x_forwarded_port: str = Header(None),
    client_code: str = Header(..., alias="clientCode"),
):
    result = await MetaCampaignService.generate_campaign(
        data_object_id=request.dataObjectId,
        access_token=authorization,
        client_code=client_code,
        business_name=request.businessName,
        goal=request.goal,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    return {
        "status": "success",
        "data": result
    }

# Create Meta Campaign

@router.post("/meta-campaign/create")
async def create_meta_campaign(
    request: MetaCampaignRequest,
    authorization: str = Header(...),
):
    result = await MetaCampaignCreateService.create_campaign(
        ad_account_id=request.adAccountId,
        access_token=authorization,
        campaign_payload=request.campaignPayload
    )

    return {
        "status": "success",
        "data": {
            "campaignId": result.get("id")
        }
    }

    # Genrerate Meta Ad-Set

@router.post("/meta-adset/service")
async def generate_meta_adset(
    request: MetaAdSetRequest,
    authorization: str = Header(...),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(None),
    x_forwarded_port: str = Header(None),
):
    result = await MetaAdSetService.generate_adset(
        data_object_id=request.dataObjectId,
        access_token=authorization,
        client_code=client_code,
        goal=request.goal,
        region=request.region,
        ad_account_id=request.adAccountId,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    return {
        "status": "success",
        "data": result
    }

# Create Meta Ad-Set

@router.post("/meta-adset/create")
async def create_meta_adset(
    request: MetaAdSetRequest,
    meta_access_token: str = Header(..., alias="meta-access-token"),
):
    result = await MetaAdSetCreateService.create_adset(
        ad_account_id=request.adAccountId,
        access_token=meta_access_token,
        campaign_id=request.campaignId,
        adset_payload=request.adsetPayload
    )

    return {
        "status": "success",
        "data": {"adsetId": result.get("id")}
    }

# Generate Meta Ad Image

@router.post("/meta-ad-image/service")
async def meta_ad_image_service(
    request: MetaAdImageRequest,
    authorization: str = Header(...),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(None),
    x_forwarded_port: str = Header(None),
):
    result = await MetaAdImageService.generate_images(
        data_object_id=request.dataObjectId,
        access_token=authorization,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    return {
        "status": "success",
        "data": result
    }


# Upload Meta Ad Image

@router.post("/meta-ad-image/create")
async def create_meta_ad_image(
    request: MetaAdImageRequest,
    meta_access_token: str = Header(..., alias="meta-access-token"),
):
    result = await MetaAdImageCreateService.upload_image(
        ad_account_id=request.adAccountId,
        access_token=meta_access_token,
        image_url=request.imageUrl
    )

    return {
        "status": "success",
        "data": result
    }


# Generate Meta Creative

@router.post("/meta-creative/service")
async def generate_meta_creative(
    request: MetaCreativeRequest,
    authorization: str = Header(...),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(None),
    x_forwarded_port: str = Header(None),
):
    result = await MetaCreativePipeline.generate_creative(
        data_object_id=request.dataObjectId,
        access_token=authorization,
        client_code=client_code,
        logo_url=request.logoUrl,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )

    return {
        "status": "success",
        "data": result
    }
