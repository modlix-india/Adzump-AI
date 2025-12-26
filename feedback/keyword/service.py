
from typing import List, Optional
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_engine
from .models import KeywordFeedback, RejectedKeyword
from ..common.models import FeedbackAction
from rag import EmbeddingService
from structlog import get_logger    #type: ignore

logger = get_logger(__name__)

class KeywordFeedbackService:
    REJECTION_COLLECTION = "keyword_rejections"
    ACCEPTANCE_COLLECTION = "keyword_acceptances"
    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(self):
        self.engine = get_engine()
        self.embedding_svc = EmbeddingService()

    async def record_keyword_feedback(
        self, client_code: str, feedback: KeywordFeedback
    ) -> UUID:
        if feedback.action == FeedbackAction.REJECTED and not feedback.comment:
            raise ValueError("comment is required when action is 'rejected'")

        collection_name = (
            self.REJECTION_COLLECTION
            if feedback.action == FeedbackAction.REJECTED
            else self.ACCEPTANCE_COLLECTION
        )

        metadata = feedback.to_metadata(client_code)

        chunk_id = await self.embedding_svc.ingest_content(
            collection_name=collection_name,
            external_id=f"{client_code}:{feedback.business_type or 'default'}",  # One doc per client+business_type
            content=feedback.to_embedding_text(),
            metadata=metadata,
            source="keyword_feedback",
            description=f"Keyword {collection_name.split('_')[1]} feedback",
        )

        logger.info(
            f"Recorded feedback for '{feedback.keyword}' "
            f"(action={feedback.action.value}, client={client_code})"
        )
        return chunk_id

    # TO DO: need work on this
    async def get_rejected_keywords(
        self,
        client_code: str,
        keyword_type: Optional[str] = None,
        business_type: Optional[str] = None,
    ) -> List[RejectedKeyword]:
        
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
                "client_code": client_code,
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
                    created_at=row.created_at,
                )
                for row in rows
            ]

            logger.info(
                f"Retrieved {len(rejected)} rejected keywords for {client_code}"
            )
            return rejected

    # TO DO: need work on this
    def build_rejection_context(
        self, rejected: List[RejectedKeyword], limit: int = 50
    ) -> str:
        """Build context string for LLM prompt"""
        if not rejected:
            return ""

        context_parts = [
            "## PREVIOUSLY REJECTED KEYWORDS",
            "",
            "The user has rejected the following keywords. DO NOT suggest these or very similar keywords:",
            "",
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
                context_parts.append(f'- "{item.keyword}"{reason}')
            context_parts.append("")

        return "\n".join(context_parts)
