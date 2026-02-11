import sys
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from services.google_kw_update_service.google_kw_seed_expander import (
    EnhancedSeedExpander,
)
from third_party.google.models.keyword_model import Keyword


@pytest.mark.asyncio
async def test_expand_seed_keywords_success():
    # Setup
    expander = EnhancedSeedExpander()
    good_keywords = [
        Keyword(
            keyword="villa sarjapur",
            criterion_id="123",
            match_type="phrase",
            ad_group_id="456",
            ad_group_name="Ad Group 1",
            campaign_id="789",
            campaign_name="Campaign 1",
            status="ENABLED",
            impressions=100,
            clicks=10,
            conversions=2,
            cost=100.0,
            ctr=10.0,
            average_cpc=10.0,
            cpl=50.0,
            conv_rate=20.0,
            quality_score=10,
        ),
    ]
    business_context = {
        "brand_info": MagicMock(
            brand_name="Adzump",
            business_type="Real Estate Developer",
            primary_location="Bangalore",
            service_areas=["Sarjapur", "Whitefield"],
        ),
        "unique_features": ["Luxury villas", "Prime location"],
    }

    # Mock LLM call
    mock_llm_response = MagicMock()
    mock_llm_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"keywords": ["luxury villa bangalore", "premium villa sarjapur"]}'
            )
        )
    ]

    # Mock Autocomplete call
    mock_autocomplete_results = [
        "luxury villa bangalore price",
        "premium villa sarjapur road",
    ]

    with (
        patch(
            "services.google_kw_update_service.google_kw_seed_expander.chat_completion",
            new_callable=AsyncMock,
        ) as mock_llm,
        patch(
            "services.google_kw_update_service.google_kw_seed_expander.google_autocomplete.batch_fetch_autocomplete_suggestions",
            new_callable=AsyncMock,
        ) as mock_auto,
    ):
        mock_llm.return_value = mock_llm_response
        mock_auto.return_value = mock_autocomplete_results

        # Execute
        results = await expander.expand_seed_keywords(good_keywords, business_context)

        # Verify
        assert len(results) > 1
        assert "villa sarjapur" in results
        assert "luxury villa bangalore" in results
        assert "premium villa sarjapur" in results
        assert "luxury villa bangalore price" in results
        assert "premium villa sarjapur road" in results

        # Check deduplication (add a duplicate)
        with patch.object(
            expander,
            "_generate_llm_seeds",
            return_value=["villa sarjapur", "new keyword"],
        ):
            with patch.object(
                expander,
                "_expand_with_autocomplete",
                return_value=["villa sarjapur", "another keyword"],
            ):
                dedup_results = await expander.expand_seed_keywords(
                    good_keywords, business_context
                )
                assert (
                    len(dedup_results) == 3
                )  # villa sarjapur, new keyword, another keyword
                assert dedup_results.count("villa sarjapur") == 1
