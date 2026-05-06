import unittest
from unittest.mock import AsyncMock, patch, MagicMock

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
    @patch(
        "services.competitor.competitor_analysis_orchestrator.competitor_insight_service"
    )
    async def test_analyze_all_competitors_flow(
        self, mock_insight, mock_storage, mock_analyze_comp
    ):
        """Verify the V3 high-level orchestration flow."""
        # 1. Mock Storage Response
        mock_storage.read_page_storage = AsyncMock()
        mock_storage.update_storage = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.content = [self.record]
        mock_storage.read_page_storage.return_value = mock_resp

        # 2. Mock Discovery Result
        mock_analyze_comp.return_value = Competitor(
            name="Comp1",
            url="https://comp1.com",
            pages_scraped=1,
            extracted_keywords=[
                CompetitorKeyword(
                    keyword="project management",
                    match_type="PHRASE",
                    volume=1000,
                    source="discovery",
                )
            ],
            summary="Test summary",
        )

        # 3. Mock Insight Service
        mock_insight.enrich_competitor_keyword_trends = AsyncMock(
            return_value=[
                CompetitorKeyword(
                    keyword="project management",
                    volume=1000,
                    source="discovery",
                    trend_direction="rising",
                )
            ]
        )
        mock_insight.rate_keyword_potential = AsyncMock(
            side_effect=lambda enriched_keywords, business_metadata: [
                kw.model_copy(update={"opportunity_score": 90})
                for kw in enriched_keywords
            ]
        )

        # 4. Run Orchestration
        result = await self.orchestrator.start_competitor_analysis(
            business_url="https://example.com",
            customer_id="123",
            login_customer_id="456",
        )

        # 5. Assertions
        self.assertIsInstance(result, CompetitorAnalysisResult)
        self.assertEqual(len(result.competitor_analysis), 1)
        self.assertEqual(result.enriched_keywords[0].opportunity_score, 90)
        mock_storage.update_storage.assert_called_once()

    @patch(
        "services.competitor.competitor_discovery_service.competitor_discovery_service.find_keywords_for_competitor"
    )
    @patch("services.competitor.competitor_analysis_orchestrator.storage_service")
    @patch(
        "services.competitor.competitor_analysis_orchestrator.competitor_insight_service"
    )
    async def test_enrich_flow_separately(
        self, mock_insight, mock_storage, mock_analyze_comp
    ):
        """Verify the direct aggregation flow."""
        # Mock Storage
        mock_storage.read_page_storage = AsyncMock()
        mock_storage.update_storage = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.success = True
        mock_resp.content = [self.record]
        mock_storage.read_page_storage.return_value = mock_resp

        # Mock Insight
        mock_insight.enrich_competitor_keyword_trends = AsyncMock(return_value=[])
        mock_insight.rate_keyword_potential = AsyncMock(return_value=[])

        # Run internal method
        await self.orchestrator._load_user_business_context(
            business_url="https://example.com"
        )

        # Run aggregation with new name
        await self.orchestrator._enrich_competitor_keyword_with_trends_and_save(
            competitors=[],
            user_business_info=self.brand_info,
            storage_id="123",
            customer_id="456",
            login_customer_id="789",
            business_url="https://example.com",
        )

    @patch("services.competitor.competitor_discovery_service.helpers")
    @patch("services.competitor.competitor_discovery_service.scraper_service")
    @patch("services.competitor.competitor_discovery_service.BusinessService")
    @patch("services.competitor.competitor_discovery_service.GoogleKeywordService")
    @patch(
        "services.competitor.competitor_discovery_service.google_autocomplete"
    )
    @patch("services.competitor.competitor_discovery_service.keyword_planner_adapter")
    async def test_discovery_decomposition(
        self,
        mock_planner,
        mock_autocomplete_module,
        mock_kw_service,
        mock_business_service,
        mock_scraper,
        mock_helpers,
    ):
        """Verify V3 discovery: Seeds -> Expansion -> Enrichment -> Filter."""
        # Instantiate inside to pick up the patches in __init__
        discovery_service = CompetitorDiscoveryService()

        # Mock Domain Validation
        mock_helpers.validate_domain_exists = AsyncMock(
            return_value=(True, None)
        )

        # Mock Scraper
        mock_scraper.scrape = AsyncMock()
        mock_scraper.scrape.return_value.success = True
        mock_scraper.scrape.return_value.data = {
            "title": "Comp1",
            "links": [{"href": "/pricing", "text": "Pricing Plans"}],
            "text": "content",
        }

        # Mock BusinessService
        mock_biz = mock_business_service.return_value
        mock_biz.generate_website_summary = AsyncMock(
            return_value='{"summary": "Comp1 is a premium tool for teams."}'
        )
        mock_biz.extract_business_metadata = AsyncMock(
            return_value=BusinessMetadata(brand_name="Comp1")
        )
        mock_biz.extract_business_unique_features = AsyncMock(return_value=["Feature1"])

        # Mock GoogleKeywordService
        mock_kw = mock_kw_service.return_value
        mock_kw.generate_seed_keywords = AsyncMock(
            side_effect=[["brand seed"], ["generic seed"]]
        )

        # Mock Autocomplete
        mock_autocomplete_module.batch_fetch_autocomplete_suggestions = AsyncMock(
            return_value=["expanded seed"]
        )

        # Mock Keyword Planner
        mock_planner.generate_keyword_ideas = AsyncMock(
            return_value=[
                {
                    "keyword": "management tool",
                    "volume": 500,
                    "competition": "MEDIUM",
                    "competitionIndex": 0.5,
                }
            ]
        )

        # Mock selection/filtering
        from models.keyword_model import OptimizedKeyword, MatchType

        mock_kw.select_positive_keywords = AsyncMock(
            return_value=[
                OptimizedKeyword(
                    keyword="management tool",
                    volume=500,
                    competition="MEDIUM",
                    competitionIndex=0.5,
                    match_type=MatchType.PHRASE,
                    rationale="High intent",
                )
            ]
        )

        with patch(
            "utils.competitor_extraction.select_strategic_pages",
            AsyncMock(return_value=[]),
        ):
            # Run Discovery
            comp = await discovery_service.find_keywords_for_competitor(
                competitor_info=Competitor(name="Comp1", url="https://comp1.com"),
                customer_id="123",
                login_customer_id="456",
            )

            # Verify Results
            self.assertEqual(comp.name, "Comp1")
            self.assertEqual(comp.summary, "Comp1 is a premium tool for teams.")
            # Now we expect 2 keywords (1 Brand, 1 Generic)
            self.assertEqual(len(comp.extracted_keywords), 2)
            self.assertEqual(comp.extracted_keywords[0].keyword, "management tool")
            self.assertEqual(comp.extracted_keywords[0].category, "Brand")
            self.assertEqual(comp.extracted_keywords[1].category, "Generic")

            # Verify calls
            mock_kw.generate_seed_keywords.assert_called()
            # Each branch calls autocomplete and planner
            self.assertEqual(
                mock_autocomplete_module.batch_fetch_autocomplete_suggestions.call_count, 2
            )
            self.assertEqual(mock_planner.generate_keyword_ideas.call_count, 2)


if __name__ == "__main__":
    unittest.main()
