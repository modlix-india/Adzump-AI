from fastapi import APIRouter, Body
from services.competitor.competitor_analysis_orchestrator import (
    competitor_analysis_orchestrator,
)
from utils.response_helpers import success_response, error_response

router = APIRouter(prefix="/api/ds/competitor", tags=["competitor"])


@router.post("/analyze")
async def analyze_competitors(
    business_url: str = Body(..., embed=True),
    customer_id: str = Body(..., embed=True),
    login_customer_id: str = Body(..., embed=True),
    force_fresh_analysis: bool = False,
):
    """Run competitor keyword analysis synchronously."""
    result = await competitor_analysis_orchestrator.start_competitor_analysis(
        business_url=business_url,
        customer_id=customer_id,
        login_customer_id=login_customer_id,
        force_fresh_analysis=force_fresh_analysis,
    )

    if not result.competitor_analysis:
        return error_response("Competitor analysis failed or no competitors found.")

    return success_response(result)
