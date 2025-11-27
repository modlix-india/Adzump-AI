from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from ..common.models import FeedbackAction, RejectionCategory

class KeywordFeedback(BaseModel):
    session_id: Optional[str] = None
    keyword: str
    keyword_type: str = Field(..., description="'brand' or 'generic'")
    action: FeedbackAction
    rejection_reason: Optional[str] = None
    rejection_category: Optional[RejectionCategory] = None
    user_comment: Optional[str] = None
    
    # Context fields (optional but useful for filtering)
    business_type: Optional[str] = None
    primary_location: Optional[str] = None
    url: Optional[str] = None
    
    # Metric fields (optional)
    match_type: Optional[str] = None
    volume: Optional[int] = None
    competition_index: Optional[int] = None
    
    def to_embedding_text(self) -> str:
        """Create rich text representation for vector embedding"""
        parts = [
            f"Keyword: {self.keyword}",
            f"Type: {self.keyword_type}",
            f"Action: {self.action.value}"
        ]
        
        if self.business_type:
            parts.append(f"Business: {self.business_type}")
        
        if self.primary_location:
            parts.append(f"Location: {self.primary_location}")
        
        if self.action == FeedbackAction.REJECTED:
            if self.rejection_category:
                parts.append(f"Category: {self.rejection_category.value}")
            if self.rejection_reason:
                parts.append(f"Reason: {self.rejection_reason}")
            if self.user_comment:
                parts.append(f"Comment: {self.user_comment}")
        
        return " | ".join(parts)

class RejectedKeyword(BaseModel):
    keyword: str
    rejection_reason: Optional[str]
    rejection_category: Optional[str]
    created_at: datetime
