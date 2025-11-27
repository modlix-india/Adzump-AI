import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_engine
from .models import KeywordFeedback, RejectedKeyword
from ..common.models import FeedbackAction
from rag.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

class KeywordFeedbackService:
    
    REJECTION_COLLECTION = "keyword_rejections"
    ACCEPTANCE_COLLECTION = "keyword_acceptances"
    EMBEDDING_MODEL = "text-embedding-3-small"
    
    def __init__(self):
        self.engine = get_engine()
        
    async def record_keyword_feedback(
        self, 
        client_code: str,
        feedback: KeywordFeedback
    ) -> UUID:
        """
        Record single keyword feedback.
        Creates Level 1 chunk only (exact keyword feedback).
        
        Raises:
            ValueError: If validation fails (e.g., missing rejection_reason)
            SQLAlchemyError: If database operation fails
        """
        # Validate business rules
        if feedback.action == FeedbackAction.REJECTED and not feedback.rejection_reason:
            raise ValueError("rejection_reason is required when action is 'rejected'")
        
        # Determine collection based on action
        collection_name = (
            self.REJECTION_COLLECTION 
            if feedback.action == FeedbackAction.REJECTED 
            else self.ACCEPTANCE_COLLECTION
        )
        
        # Build metadata (Level 1 structure)
        metadata = {
            "match_level": "exact",  # Level 1
            "keyword": feedback.keyword.lower().strip(),
            "keyword_type": feedback.keyword_type,
            "action": feedback.action.value,
            "rejection_reason": feedback.rejection_reason,
            "rejection_category": feedback.rejection_category.value if feedback.rejection_category else None,
            "user_comment": feedback.user_comment,
            "business_type": feedback.business_type,
            "primary_location": feedback.primary_location,
            "url": feedback.url,
            "match_type": feedback.match_type,
            "volume": feedback.volume,
            "competition_index": feedback.competition_index,
            "client_code": client_code,
            "session_id": feedback.session_id,
            "is_active": True
        }
        
        # Use EmbeddingService to ingest content
        embedding_svc = EmbeddingService()
        chunk_id = await embedding_svc.ingest_content(
            collection_name=collection_name,
            external_id=f"{client_code}:{feedback.session_id or 'default'}",
            content=feedback.to_embedding_text(),
            metadata=metadata,
            source="keyword_feedback",
            description=f"Keyword {collection_name.split('_')[1]} feedback"
        )
        
        logger.info(
            f"Recorded feedback for '{feedback.keyword}' "
            f"(action={feedback.action.value}, client={client_code})"
        )
        return chunk_id
    
    # ==================== RETRIEVAL (Level 1 Exact Match) ====================
    
    async def get_rejected_keywords(
        self,
        client_code: str,
        keyword_type: Optional[str] = None,
        business_type: Optional[str] = None
    ) -> List[RejectedKeyword]:
        """
        Get all rejected keywords for a client (Level 1 exact match).
        Used to filter out keywords before generation.
        
        Raises:
            ValueError: If keyword_type is invalid
            SQLAlchemyError: If database operation fails
        """
        # Validate keyword_type
        if keyword_type and keyword_type not in ["brand", "generic"]:
            raise ValueError("keyword_type must be either 'brand' or 'generic'")
        
        async with AsyncSession(self.engine) as session:
            query = """
                SELECT 
                    c.metadata->>'keyword' as keyword,
                    c.metadata->>'rejection_reason' as rejection_reason,
                    c.metadata->>'rejection_category' as rejection_category,
                    c.created_at
                FROM rag_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                JOIN rag_collections col ON d.collection_id = col.id
                WHERE col.name = :collection_name
                    AND c.metadata->>'client_code' = :client_code
                    AND c.metadata->>'is_active' = 'true'
            """
            
            params = {
                "collection_name": self.REJECTION_COLLECTION,
                "client_code": client_code
            }
            
            if keyword_type:
                query += " AND c.metadata->>'keyword_type' = :keyword_type"
                params["keyword_type"] = keyword_type
            
            if business_type:
                query += " AND c.metadata->>'business_type' = :business_type"
                params["business_type"] = business_type
            
            query += " ORDER BY c.created_at DESC"
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            rejected = [
                RejectedKeyword(
                    keyword=row.keyword,
                    rejection_reason=row.rejection_reason,
                    rejection_category=row.rejection_category,
                    created_at=row.created_at
                )
                for row in rows
            ]
            
            logger.info(f"Retrieved {len(rejected)} rejected keywords for {client_code}")
            return rejected
    
    def build_rejection_context(self, rejected: List[RejectedKeyword], limit: int = 50) -> str:
        """Build context string for LLM prompt"""
        if not rejected:
            return ""
        
        context_parts = [
            "## PREVIOUSLY REJECTED KEYWORDS",
            "",
            "The user has rejected the following keywords. DO NOT suggest these or very similar keywords:",
            ""
        ]
        
        # Group by category
        by_category: dict[str, List[RejectedKeyword]] = {}
        for item in rejected[:limit]:
            category = item.rejection_category or "other"
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(item)
        
        for category, items in by_category.items():
            context_parts.append(f"### {category.upper().replace('_', ' ')}")
            for item in items[:10]:  # Limit per category
                reason = f" - {item.rejection_reason}" if item.rejection_reason else ""
                context_parts.append(f"- \"{item.keyword}\"{reason}")
            context_parts.append("")
        
        return "\n".join(context_parts)
