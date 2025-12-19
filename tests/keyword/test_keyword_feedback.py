"""
Comprehensive unit tests for KeywordFeedbackService.

Tests embedding insertion, metadata correctness, and retrieval
from a real PostgreSQL database.
"""

import pytest  # type: ignore
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from feedback.keyword import KeywordFeedbackService, KeywordFeedback
from feedback.common import FeedbackAction, RejectionCategory


@pytest.mark.asyncio
async def test_successful_rejection_feedback_insertion(
    feedback_service: KeywordFeedbackService, sample_rejection_feedback: KeywordFeedback
):
    client_code = "TEST_CLIENT_001"

    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=client_code, feedback=sample_rejection_feedback
    )

    assert chunk_id is not None
    assert isinstance(chunk_id, UUID)

    async with AsyncSession(feedback_service.engine) as session:
        result = await session.execute(
            text("SELECT id, content, embedding FROM rag_chunks WHERE id = :chunk_id"),
            {"chunk_id": chunk_id},
        )
        row = result.fetchone()
        print(f"[DEBUG] DB Row: {row}")
        assert row is not None, f"Chunk {chunk_id} not found in database"
        assert row.embedding is not None, "Embedding is NULL"


@pytest.mark.asyncio
async def test_successful_acceptance_feedback_insertion(
    feedback_service: KeywordFeedbackService,
    sample_acceptance_feedback: KeywordFeedback,
):
    client_code = "TEST_CLIENT_002"

    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=client_code, feedback=sample_acceptance_feedback
    )

    assert chunk_id is not None
    assert isinstance(chunk_id, UUID)


@pytest.mark.asyncio
async def test_rejection_without_reason_raises_error(
    feedback_service: KeywordFeedbackService,
):
    invalid_feedback = KeywordFeedback(
        keyword="test keyword",
        keyword_type="generic",
        action=FeedbackAction.REJECTED,
        rejection_category=RejectionCategory.IRRELEVANT,
        comment=None,  # Missing!
        business_type="Test Business",
        url="https://example.com",
        match_type="BROAD",
        volume=5000,
        competition_index=85,
    )

    with pytest.raises(
        ValueError, match="comment is required when action is 'rejected'"
    ):
        await feedback_service.record_keyword_feedback(
            client_code="TEST_CLIENT_003", feedback=invalid_feedback
        )


@pytest.mark.asyncio
async def test_acceptance_without_reason_succeeds(
    feedback_service: KeywordFeedbackService,
):
    client_code = "TEST_CLIENT_004"
    feedback = KeywordFeedback(
        keyword="good keyword",
        keyword_type="brand",
        action=FeedbackAction.ACCEPTED,
        business_type="Test Business",
    )

    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=client_code, feedback=feedback
    )

    assert chunk_id is not None


@pytest.mark.asyncio
async def test_embedding_vector_is_generated_and_stored(
    feedback_service: KeywordFeedbackService,
    test_session: AsyncSession,
    sample_rejection_feedback: KeywordFeedback,
):
    client_code = "TEST_CLIENT_005"

    chunk_id = await feedback_service.record_keyword_feedback(
        client_code=client_code, feedback=sample_rejection_feedback
    )

    result = await test_session.execute(
        text("SELECT embedding FROM rag_chunks WHERE id = :chunk_id"),
        {"chunk_id": chunk_id},
    )
    row = result.fetchone()

    assert row is not None
    assert row.embedding is not None
    # OpenAI text-embedding-3-small produces 1536-dimensional vectors
    assert len(row.embedding) == 1536