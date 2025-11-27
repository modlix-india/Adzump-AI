import logging

from fastapi import APIRouter, Header, status, Depends

from .service import KeywordFeedbackService
from .models import KeywordFeedback
from utils.response_helpers import success_response

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ds/feedback/keyword",
    tags=["feedback-keyword"]
)


def get_feedback_service() -> KeywordFeedbackService:
    return KeywordFeedbackService()

async def verify_client_access(client_code: str = Header(..., alias="clientCode")):
    return {"client_code": client_code}

@router.post("/", status_code=status.HTTP_201_CREATED)
async def submit_keyword_feedback(
    feedback: KeywordFeedback,
    client_context: dict = Depends(verify_client_access),
    feedback_service: KeywordFeedbackService = Depends(get_feedback_service)
):
    """Submit single keyword feedback (accept or reject)."""
    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=client_context["client_code"],
        feedback=feedback
    )
    
    return success_response({
        "message": f"Recorded feedback for keyword '{feedback.keyword}'",
        "feedback_id": str(chunk_id),
        "action": feedback.action.value
    })
