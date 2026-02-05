from fastapi import APIRouter

from core.infrastructure.context import auth_context
from agents.optimization.age_optimization_agent import age_optimization_agent

router = APIRouter(prefix="/api/ds/optimize", tags=["optimization"])


@router.post("/age")
async def generate_age_optimization():
    result = await age_optimization_agent.generate_recommendations(
        client_code=auth_context.client_code,
    )
    return {"status": "success", "data": result}
