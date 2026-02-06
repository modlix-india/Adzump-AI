import asyncio
from structlog import get_logger

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import (
    CampaignRecommendation,
    OptimizationFields,
    KeywordRecommendation,
    SearchTermAnalysis,
)
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.search_term import GoogleSearchTermAdapter
from core.services.search_term_analyzer import SearchTermAnalyzer
from core.services.recommendation_storage import recommendation_storage_service

logger = get_logger(__name__)


class SearchTermOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.search_term_adapter = GoogleSearchTermAdapter()
        self.analyzer = SearchTermAnalyzer()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        campaign_mapping = await campaign_mapping_service.get_campaign_mapping_with_summary(client_code)

        results = await asyncio.gather(*[
            self._process_account(acc, campaign_mapping) for acc in accounts
        ])
        all_recs = [r for recs in results for r in recs]

        for rec in all_recs:
            await recommendation_storage_service.store(rec, client_code)

        return {"recommendations": [r.model_dump() for r in all_recs]}

    async def _process_account(self, account: dict, campaign_mapping: dict) -> list[CampaignRecommendation]:
        account_id = account["customer_id"]
        parent_id = account["login_customer_id"]

        search_terms = await self.search_term_adapter.fetch_search_terms(account_id, parent_id)
        if not search_terms:
            return []

        campaigns = self._group_by_campaign(search_terms)
        logger.info("Search terms fetched", account_id=account_id, total=len(search_terms), campaigns=len(campaigns))

        recommendations = []
        for cid, data in campaigns.items():
            mapping = campaign_mapping.get(cid)
            if not mapping or not mapping.get("summary"):
                continue

            logger.info("Processing campaign", campaign_id=cid, term_count=len(data["terms"]))

            keywords, negative_keywords = await self._analyze_terms(data["terms"], mapping["summary"])
            if not keywords and not negative_keywords:
                continue

            recommendations.append(CampaignRecommendation(
                platform="google_ads",
                parent_account_id=parent_id,
                account_id=account_id,
                product_id=mapping["product_id"],
                campaign_id=cid,
                campaign_name=data["name"],
                campaign_type=data["type"],
                completed=False,
                fields=OptimizationFields(
                    keywords=keywords or None,
                    negativeKeywords=negative_keywords or None,
                ),
            ))

        logger.info("Account processed", account_id=account_id, campaigns=len(recommendations))
        return recommendations

    async def _analyze_terms(
        self, terms: list, summary: str
    ) -> tuple[list[KeywordRecommendation], list[KeywordRecommendation]]:
        results = await asyncio.gather(*[
            self.analyzer.analyze_term(summary, t["search_term"], t["metrics"])
            for t in terms
        ])

        keywords, negative_keywords = [], []
        for t, r in zip(terms, results):
            rec = KeywordRecommendation(
                text=r["text"],
                match_type=t["match_type"],
                reason=r["reason"],
                metrics=r["metrics"],
                analysis=SearchTermAnalysis(**r["analysis"]),
            )
            if r["recommendation_type"] == "positive":
                keywords.append(rec)
            else:
                negative_keywords.append(rec)

        return keywords, negative_keywords

    @staticmethod
    def _group_by_campaign(search_terms: list) -> dict[str, dict]:
        campaigns: dict[str, dict] = {}
        for term in search_terms:
            group = campaigns.setdefault(term["campaign_id"], {
                "name": term["campaign_name"],
                "type": term["campaign_type"],
                "terms": [],
            })
            group["terms"].append(term)
        return campaigns


search_term_optimization_agent = SearchTermOptimizationAgent()
