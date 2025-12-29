"""
Pytest fixtures for keyword feedback tests.
Provides sample data fixtures for testing keyword feedback functionality.
"""

import pytest
from feedback.keyword import KeywordFeedbackService, KeywordFeedback
from feedback.common import FeedbackAction, RejectionCategory


@pytest.fixture(scope="module")
def feedback_service() -> KeywordFeedbackService:
    """Provide a shared KeywordFeedbackService instance for tests."""
    return KeywordFeedbackService()


@pytest.fixture
def sample_rejection_feedback() -> KeywordFeedback:
    return KeywordFeedback(
        session_id="test-session-001",
        keyword="cheap lawyer",
        keyword_type="generic",
        action=FeedbackAction.REJECTED,
        rejection_category=RejectionCategory.IRRELEVANT,
        comment="Too price-focused, we target premium clients",
        business_type="Law Firm",
        url="https://example-lawfirm.com",
        match_type="BROAD",
        volume=5000,
        competition_index=85,
    )


@pytest.fixture
def sample_acceptance_feedback() -> KeywordFeedback:
    return KeywordFeedback(
        session_id="test-session-002",
        keyword="corporate attorney",
        keyword_type="generic",
        action=FeedbackAction.ACCEPTED,
        business_type="Law Firm",
        url="https://example-lawfirm.com",
        match_type="PHRASE",
        volume=2000,
        competition_index=75,
    )


@pytest.fixture
def sample_brand_rejection() -> KeywordFeedback:
    return KeywordFeedback(
        session_id="test-session-003",
        keyword="acme law competitors",
        keyword_type="brand",
        action=FeedbackAction.REJECTED,
        comment="Contains competitor reference",
        rejection_category=RejectionCategory.COMPETITOR,
        business_type="Law Firm",
        url="https://acmelawfirm.com",
    )