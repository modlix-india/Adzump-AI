import unittest
from unittest.mock import MagicMock, AsyncMock, patch, ANY

from models.competitor_model import (
    Competitor,
    CompetitorKeyword,
    CompetitorAnalysisResult,
)
from models.business_model import BusinessMetadata
from services.competitor.competitor_discovery_service import CompetitorDiscoveryService
from services.competitor.competitor_analysis_orchestrator import (
    CompetitorAnalysisOrchestrator,
)


class TestCompetitorOrchestration(unittest.IsolatedAsyncioTestCase):
    """Test suite for verifying competitor analysis orchestration using mocks."""

    def setUp(self):
        self.orchestrator = CompetitorAnalysisOrchestrator()
        self.discovery_service = CompetitorDiscoveryService()

        # Mock brand info
        self.brand_info = BusinessMetadata(
            brand_name="TestBrand",
            business_type="Software Service",
            business_summary="Cloud-based project management",
            unique_features=["Automated tasks", "Real-time collaboration"],
        )

        # Mock storage record
        self.record = {
            "business_url": "https://example.com",
            "competitors": [{"name": "Comp1", "url": "https://comp1.com"}],
            "summary": "Cloud software",
            "_id": "mock_id_123",
        }

    @patch(
        "services.competitor.competitor_discovery_service.competitor_discovery_service.find_keywords_for_competitor"
    )
    @patch("services.competitor.competitor_analysis_orchestrator.storage_service")
    async def test_analyze_all_competitors_flow(self, mock_storage, mock_analyze_comp):
        """Verify the V3 high-level orchestration flow."""
        # 1. Mock Storage Response
        mock_storage.read_page_storage = AsyncMock()
        mock_storage.update_storage = AsyncMock()
        mock_storage.read_page_storage.return_value.success = True
        mock_storage.read_page_storage.return_value.result = [
            {"result": {"result": {"content": [self.record]}}}
        ]

        # 2. Mock Discovery Result (Now returns enriched keywords)
        mock_analyze_comp.return_value = Competitor(
            name="Comp1",
            url="https://comp1.com",
            pages_scraped=1,
            extracted_keywords=[
                CompetitorKeyword(
                    keyword="project management",
                    volume=1000,
                    source="discovery",
                    category="Core",
                )
            ],
        )

        # 3. Mock Insight Service (For Orchestrator's Aggregate Pass)
        with patch(
            "services.competitor.competitor_analysis_orchestrator.competitor_insight_service"
        ) as mock_insight:
            # Aggregate pass: Trends + Final Score
            mock_insight.add_volume_and_trends = AsyncMock(
                return_value=[
                    CompetitorKeyword(
                        keyword="project management",
                        volume=1000,
                        source="discovery",
                        category="Core",
                        trend_direction="rising",
                    )
                ]
            )
            mock_insight.rate_keyword_potential = AsyncMock(
                side_effect=lambda kws, b: [
                    kw for kw in kws if (setattr(kw, "opportunity_score", 90) or True)
                ]
            )

            # Run Orchestration
            result = await self.orchestrator.start_competitor_analysis(
                business_url="https://example.com",
                customer_id="123",
                login_customer_id="456",
            )

            # Verify Results
            self.assertIsInstance(result, CompetitorAnalysisResult)
            self.assertEqual(len(result.competitor_analysis), 1)
            self.assertEqual(result.enriched_keywords[0].opportunity_score, 90)
            self.assertEqual(result.enriched_keywords[0].trend_direction, "rising")

            # Verify credentials were passed to discovery
            mock_analyze_comp.assert_called_once_with(
                competitor_info=self.record["competitors"][0],
                record=self.record,
                brand_info=ANY,
                customer_id="123",
                login_customer_id="456",
            )

    @patch("services.competitor.competitor_discovery_service.validate_domain_exists")
    @patch("services.competitor.competitor_discovery_service.scraper_service")
    @patch("services.openai_client.chat_completion")
    @patch(
        "services.competitor.competitor_discovery_service.batch_fetch_autocomplete_suggestions"
    )
    async def test_discovery_decomposition(
        self, mock_autocomplete, mock_chat, mock_scraper, mock_validate_domain
    ):
        """Verify V3 discovery: Seeds -> Expansion -> Enrichment -> Filter."""
        # Mock Domain Validation
        mock_validate_domain.return_value = (True, None)

        # Mock Scraper
        mock_scraper.scrape = AsyncMock()
        mock_scraper.scrape.return_value.success = True
        mock_scraper.scrape.return_value.data = {
            "title": "Comp1",
            "headings": {"h1": ["Project Tool"]},
            "links": [{"href": "/pricing", "text": "Pricing Plans"}],
            "text": "content",
        }

        # Mock LLM Responses
        # 1. Strategic Seeds (Returns Seeds + Summary)
        # 2. Strategic Filter (Accepts Summary)
        mock_chat.side_effect = [
            # Link Selection
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"selection": [{"url": "https://comp1.com/pricing", "reason": "Strategic page"}]}'
                        )
                    )
                ]
            ),
            # Seed Generation
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"seeds": ["management tool"], "summary": "Comp1 is a premium tool for teams."}'
                        )
                    )
                ]
            ),
            # Strategic Filter
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"recommendations": [{"keyword": "management tool", "opportunity_score": 85, "intent": "Commercial", "relevance": 0.9, "category": "Core"}]}'
                        )
                    )
                ]
            ),
        ]

        # Mock Autocomplete
        mock_autocomplete.return_value = ["best management tool"]

        # Mock Insight Service (called inside discovery)
        with patch(
            "services.competitor.competitor_discovery_service.competitor_insight_service"
        ) as mock_insight:
            mock_insight.add_volume_and_trends = AsyncMock(
                return_value=[CompetitorKeyword(keyword="management tool", volume=500)]
            )

            # Run Discovery
            comp = await self.discovery_service.find_keywords_for_competitor(
                competitor_info={"name": "Comp1", "url": "https://comp1.com"},
                record=self.record,
                brand_info=self.brand_info,
                customer_id="123",
                login_customer_id="456",
            )

            # Verify Results
            self.assertEqual(comp.name, "Comp1")
            self.assertEqual(comp.summary, "Comp1 is a premium tool for teams.")
            self.assertEqual(len(comp.extracted_keywords), 1)
            self.assertEqual(comp.extracted_keywords[0].keyword, "management tool")
            self.assertEqual(comp.extracted_keywords[0].volume, 500)


if __name__ == "__main__":
    unittest.main()
