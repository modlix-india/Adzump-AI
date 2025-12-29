from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from ..common.models import FeedbackAction, RejectionCategory


class KeywordFeedback(BaseModel):
    session_id: Optional[str] = None
    keyword: str
    keyword_type: str = Field(..., description="'brand' or 'generic'")
    action: FeedbackAction
    rejection_category: Optional[RejectionCategory] = None
    comment: Optional[str] = None

    # Context fields (optional but useful for filtering)
    business_type: Optional[str] = None
    url: Optional[str] = None

    # Metric fields (optional)
    match_type: Optional[str] = None
    volume: Optional[int] = None
    competition_index: Optional[int] = None

    def to_embedding_text(self) -> str:
        parts = [
            f"Keyword: {self.keyword}",
            f"Type: {self.keyword_type}",
            f"Action: {self.action.value}",
        ]

        if self.business_type:
            parts.append(f"Business: {self.business_type}")

        if self.rejection_category:
            parts.append(f"Category: {self.rejection_category.value}")
        if self.comment:
            parts.append(f"Comment: {self.comment}")

        return " | ".join(parts)

    def to_metadata(self, client_code: str) -> dict:
        return {
            "match_level": "exact",
            "keyword": self.keyword.lower().strip(),
            "keyword_type": self.keyword_type,
            "action": self.action.value,
            "rejection_category": self.rejection_category.value
            if self.rejection_category
            else None,
            "comment": self.comment,
            "business_type": self.business_type,
            "url": self.url,
            "match_type": self.match_type,
            "volume": self.volume,
            "competition_index": self.competition_index,
            "client_code": client_code,
            "session_id": self.session_id,
            "is_active": True,
        }


class RejectedKeyword(BaseModel):
    keyword: str
    rejection_reason: Optional[str]
    rejection_category: Optional[str]
    created_at: datetime
