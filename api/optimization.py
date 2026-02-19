from fastapi import APIRouter, Query
from core.models.optimization import CampaignRecommendation, MutationResponse
from core.services.google_ads_mutation_service import (
    google_ads_mutation_service,
)
from core.infrastructure.context import auth_context
from agents.optimization.age_optimization_agent import age_optimization_agent
from agents.optimization.search_term_optimization_agent import (
    search_term_optimization_agent,
)
from agents.optimization.keyword_optimization_agent import (
    keyword_optimization_agent,
)
from agents.optimization.location_optimization_agent import (
    location_optimization_agent,
)
from agents.optimization.gender_optimization_agent import gender_optimization_agent

router = APIRouter(prefix="/api/ds/optimize", tags=["optimization"])


@router.post("/age")
async def generate_age_optimization():
    result = await age_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}


@router.post("/search-terms")
async def generate_search_term_optimization():
    result = await search_term_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}


@router.post("/keywords")
async def generate_keyword_optimization():
    result = await keyword_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}


@router.post("/locations")
async def generate_location_optimization():
    result = await location_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}


@router.post("/gender")
async def generate_gender_optimization():
    result = await gender_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}


@router.post("/execute", response_model=MutationResponse)
async def execute_google_ads_mutation(
    campaign: CampaignRecommendation,
    is_partial: bool = Query(False, alias="isPartial"),
):
    """Executes the campaign recommendation with optional partial apply."""
    return await google_ads_mutation_service.execute_mutation(
        campaign=campaign, is_partial=is_partial
    )


@router.post("/execute/validate", response_model=MutationResponse)
async def validate_google_ads_mutation(
    campaign: CampaignRecommendation,
):
    """Dry-run validation of the campaign recommendation."""
    return await google_ads_mutation_service.validate_mutation(campaign=campaign)
