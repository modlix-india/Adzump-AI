import os
import json
import logging
import requests
from services.search_term_analyzer import analyze_search_term_performance
from utils.date_utils import format_duration_clause
from third_party.google.services.keywords_service import fetch_keywords_service  # import new service
from oserver.connection import fetch_google_api_token_simple

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class SearchTermPipeline:
    def __init__(
        self,
        client_code: str,
        customer_id: str,
        login_customer_id: str,
        campaign_id: str,
        duration: str,
    ):
        """
        duration can be either:
          - 'LAST_30_DAYS', 'LAST_7_DAYS', etc.
          - '01/01/2025,31/12/2025' (custom range in DD/MM/YYYY format)
        """
        self.client_code = client_code
        self.customer_id = customer_id
        self.login_customer_id = login_customer_id
        self.campaign_id = campaign_id
        self.duration = duration.strip()
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        self.access_token = fetch_google_api_token_simple(client_code=client_code)

    def fetch_search_terms(self, keywords: list) -> list:
        """Fetch all search terms for multiple keywords in one API call."""
        logger.info("Fetching search terms...")
        if not keywords:
            logger.warning("No keywords provided.")
            return []

        if isinstance(keywords[0], dict):
            keywords = [kw.get("keyword", "") for kw in keywords if kw.get("keyword")]

        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "Content-Type": "application/json",
        }

        def _safe_float(value):
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0

        def _safe_int(value):
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0

        try:
            duration_clause = format_duration_clause(self.duration)
            sanitized_keywords = [kw.replace("'", "\\'") for kw in keywords]
            keyword_list = "', '".join(sanitized_keywords)
            in_clause = f"('{keyword_list}')"

            query = f"""
            SELECT
                ad_group.id,
                search_term_view.search_term,
                search_term_view.status,
                segments.keyword.info.text,
                segments.search_term_match_type,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_micros,
                metrics.conversions,
                metrics.cost_per_conversion
            FROM search_term_view
            WHERE
                campaign.id = {self.campaign_id}
                AND segments.date {duration_clause}
                AND segments.keyword.info.text IN {in_clause}
            """
            response = requests.post(endpoint, headers=headers, json={"query": query})
            data = response.json()

            if "error" in data:
                err_msg = data["error"].get("message", "Unknown GAQL error")
                logger.error(f"Google Ads API error: {err_msg}")
                return []

            search_terms = []
            for row in data.get("results", []):
                metrics = row.get("metrics", {})
                search_view = row.get("searchTermView", {})
                segments = row.get("segments", {})

                term = search_view.get("searchTerm")
                keyword_text = segments.get("keyword", {}).get("info", {}).get("text")
                match_type = segments.get("searchTermMatchType")
                if not term or not keyword_text:
                    continue

                search_terms.append({
                    "searchterm": term,
                    "keyword": keyword_text,
                    "matchType": match_type,
                    "metrics": {
                        "impressions": _safe_int(metrics.get("impressions")),
                        "clicks": _safe_int(metrics.get("clicks")),
                        "ctr": _safe_float(metrics.get("ctr")),
                        "conversions": _safe_float(metrics.get("conversions")),
                        "costMicros": _safe_int(metrics.get("costMicros")),
                        "averageCpc": _safe_float(metrics.get("averageCpc")),
                        "cost": _safe_float(metrics.get("costMicros", 0)) / 1_000_000,
                        "costPerConversion": _safe_float(metrics.get("costPerConversion")),
                    },
                })

            return search_terms

        except Exception as e:
            logger.exception(f"Error fetching search terms: {e}")
            return []

    async def run_pipeline(self) -> list:
        """Full flow: fetch keywords (via new service) → fetch search terms → classify."""
        logger.info("Running full search term analysis pipeline...")

        # Directly call the new fetch_keywords_service
        keywords = await fetch_keywords_service(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            duration=self.duration,
        )

        if not keywords:
            logger.warning("No keywords found — skipping search term fetch.")
            return []

        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            logger.warning("No search terms found — skipping classification.")
            return []

        classified_terms = await analyze_search_term_performance(search_terms)
        return classified_terms
