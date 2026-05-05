import unittest
from unittest.mock import AsyncMock, patch
from models.competitor_model import Competitor, CompetitorKeyword
from services.competitor.competitor_analysis_orchestrator import CompetitorAnalysisOrchestrator

class TestCompetitorIdempotency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orchestrator = CompetitorAnalysisOrchestrator()
        
        # Valid cached competitor
        self.cached_comp = Competitor(
            name="Cached",
            url="https://cached.com",
            extracted_keywords=[CompetitorKeyword(keyword="cached kw", opportunity_score=80)]
        )
        
        # Failed/Empty cached competitor
        self.failed_comp = Competitor(
            name="Failed",
            url="https://failed.com",
            extracted_keywords=[]
        )

    @patch("services.competitor.competitor_analysis_orchestrator.competitor_discovery_service.find_keywords_for_competitor", new_callable=AsyncMock)
    async def test_skip_already_analyzed(self, mock_discovery):
        """Verify that discovery is skipped for already analyzed URLs."""
        raw_competitors = [Competitor(name="Cached", url="https://cached.com")]
        existing_analysis = [self.cached_comp]
        
        results = await self.orchestrator._find_competitor_keywords(
            raw_competitors=raw_competitors,
            existing_analysis=existing_analysis,
            customer_id="123",
            login_customer_id="456",
            force_fresh_analysis=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://cached.com")
        self.assertEqual(results[0].extracted_keywords[0].keyword, "cached kw")
        mock_discovery.assert_not_called()

    @patch("services.competitor.competitor_analysis_orchestrator.competitor_discovery_service.find_keywords_for_competitor", new_callable=AsyncMock)
    async def test_discover_new_ones(self, mock_discovery):
        """Verify that only new URLs trigger discovery."""
        raw_competitors = [
            Competitor(name="Cached", url="https://cached.com"),
            Competitor(name="New", url="https://new.com")
        ]
        existing_analysis = [self.cached_comp]
        
        # Mock discovery for the new one
        mock_discovery.return_value = Competitor(
            name="New",
            url="https://new.com",
            extracted_keywords=[CompetitorKeyword(keyword="new kw")]
        )
        
        results = await self.orchestrator._find_competitor_keywords(
            raw_competitors=raw_competitors,
            existing_analysis=existing_analysis,
            customer_id="123",
            login_customer_id="456",
            force_fresh_analysis=False
        )
        
        self.assertEqual(len(results), 2)
        urls = [r.url for r in results]
        self.assertIn("https://cached.com", urls)
        self.assertIn("https://new.com", urls)
        
        # Should only be called for the new URL
        mock_discovery.assert_called_once()
        self.assertEqual(mock_discovery.call_args[1]["competitor_info"].url, "https://new.com")

    @patch("services.competitor.competitor_analysis_orchestrator.competitor_discovery_service.find_keywords_for_competitor", new_callable=AsyncMock)
    async def test_retry_failed_discovery(self, mock_discovery):
        """Verify that discovery is re-run for previously failed (empty) entries."""
        raw_competitors = [Competitor(name="Failed", url="https://failed.com")]
        existing_analysis = [self.failed_comp]
        
        mock_discovery.return_value = Competitor(
            name="Failed", url="https://failed.com", extracted_keywords=[CompetitorKeyword(keyword="retried kw")]
        )
        
        results = await self.orchestrator._find_competitor_keywords(
            raw_competitors=raw_competitors,
            existing_analysis=existing_analysis,
            customer_id="123",
            login_customer_id="456",
            force_fresh_analysis=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].extracted_keywords[0].keyword, "retried kw")
        mock_discovery.assert_called_once()

    @patch("services.competitor.competitor_analysis_orchestrator.competitor_discovery_service.find_keywords_for_competitor", new_callable=AsyncMock)
    async def test_force_fresh_analysis(self, mock_discovery):
        """Verify that force_fresh_analysis=True ignores existing results."""
        raw_competitors = [Competitor(name="Cached", url="https://cached.com")]
        existing_analysis = [self.cached_comp]
        
        mock_discovery.return_value = Competitor(
            name="Cached", url="https://cached.com", extracted_keywords=[CompetitorKeyword(keyword="forced kw")]
        )
        
        results = await self.orchestrator._find_competitor_keywords(
            raw_competitors=raw_competitors,
            existing_analysis=existing_analysis,
            customer_id="123",
            login_customer_id="456",
            force_fresh_analysis=True
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].extracted_keywords[0].keyword, "forced kw")
        mock_discovery.assert_called_once()

if __name__ == "__main__":
    unittest.main()
