import logging

from fastapi import APIRouter, status, Depends

from dependencies.header_dependencies import CommonHeaders, get_common_headers

from .service import KeywordFeedbackService
from .models import KeywordFeedback
from utils.response_helpers import success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ds/feedback/keyword", tags=["feedback-keyword"])


def get_feedback_service() -> KeywordFeedbackService:
    return KeywordFeedbackService()


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_keyword_feedback(
    feedback: KeywordFeedback,
    headers: CommonHeaders = Depends(get_common_headers),
    feedback_service: KeywordFeedbackService = Depends(get_feedback_service),
):
    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=headers.client_code, feedback=feedback
    )

    return success_response(
        {
            "message": f"Recorded feedback for keyword '{feedback.keyword}'",
            "feedback_id": str(chunk_id),
            "action": feedback.action.value,
        }
    )
