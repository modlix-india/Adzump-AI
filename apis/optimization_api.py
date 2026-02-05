import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import structlog
from services.asset_optimization_service import AssetOptimizationService
from oserver.services.connection import fetch_google_api_token_simple

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/optimization", tags=["Optimization"])


class AnalyzeCampaignRequest(BaseModel):
    customer_id: str = Field(..., description="Google Ads customer ID")
    campaign_id: str = Field(..., description="Campaign ID to analyze")
    login_customer_id: str = Field(
        None,
        description="Login customer ID (manager account ID). Optional for standalone accounts, defaults to customer_id if not provided",
    )
    client_code: str = Field(None, description="Client code for auth (optional)")


class AnalyzeAllCampaignsRequest(BaseModel):
    customer_id: str = Field(..., description="Google Ads customer ID")
    login_customer_id: str = Field(
        None,
        description="Login customer ID (manager account ID). Optional for standalone accounts, defaults to customer_id if not provided",
    )
    client_code: str = Field(None, description="Client code for auth (optional)")


class AnalyzeCampaignResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    total_low_assets: int
    suggestions: list
    message: str = None
    status: str = "analyzed"


@router.post("/analyze-campaign", response_model=AnalyzeCampaignResponse)
async def analyze_campaign(request: AnalyzeCampaignRequest):
    logger.info(
        "Campaign optimization requested",
        customer_id=request.customer_id,
        campaign_id=request.campaign_id,
    )

    try:
        # Get access token
        access_token = await get_access_token(request.customer_id, request.client_code)

        # Use customer_id as login_customer_id if not provided (standalone account)
        login_customer_id = request.login_customer_id or request.customer_id

        # Run optimization service
        service = AssetOptimizationService()
        result = await service.analyze_campaign(
            customer_id=request.customer_id,
            campaign_id=request.campaign_id,
            access_token=access_token,
            login_customer_id=login_customer_id,
        )

        logger.info(
            "Campaign optimization completed",
            customer_id=request.customer_id,
            campaign_id=request.campaign_id,
            suggestions_count=len(result.get("suggestions", [])),
        )

        return result

    except Exception as e:
        logger.error(
            "Campaign optimization failed",
            customer_id=request.customer_id,
            campaign_id=request.campaign_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")


@router.post("/analyze-all-campaigns")
async def analyze_all_campaigns(request: AnalyzeAllCampaignsRequest):
    logger.info(
        "Bulk campaign optimization requested",
        customer_id=request.customer_id,
    )

    try:
        # Get access token
        access_token = await get_access_token(request.customer_id, request.client_code)

        # Use customer_id as login_customer_id if not provided (standalone account)
        login_customer_id = request.login_customer_id or request.customer_id

        # Run bulk optimization service
        service = AssetOptimizationService()
        result = await service.analyze_all_campaigns(
            customer_id=request.customer_id,
            access_token=access_token,
            login_customer_id=login_customer_id,
        )

        logger.info(
            "Bulk campaign optimization completed",
            customer_id=request.customer_id,
            total_campaigns=result.get("total_campaigns", 0),
            successful=result.get("successful", 0),
            failed=result.get("failed", 0),
        )

        return result

    except Exception as e:
        logger.error(
            "Bulk campaign optimization failed",
            customer_id=request.customer_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=500, detail=f"Bulk optimization failed: {str(e)}"
        )


async def get_access_token(customer_id: str, client_code: str = None) -> str:
    try:
        if client_code:
            # Production: fetch from your auth system
            token = await fetch_google_api_token_simple(client_code)
        else:
            # Development: try environment variable

            token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

            if not token:
                # Fallback to fetch_google_api_token_simple with customer_id
                token = await fetch_google_api_token_simple(customer_id)

        if not token:
            raise ValueError("Could not retrieve access token")

        return token

    except Exception as e:
        logger.error("Failed to get access token", error=str(e))
        raise HTTPException(
            status_code=401, detail="Failed to authenticate with Google Ads API"
        )
