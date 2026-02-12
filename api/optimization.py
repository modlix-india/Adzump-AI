from fastapi import APIRouter

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
