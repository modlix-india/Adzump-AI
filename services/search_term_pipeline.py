import json
import os
import requests
from services.search_term_analyzer import analyze_search_term_performance
import httpx
from utils.date_utils import format_duration_clause
import logging
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
        self.access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

        # self.access_token = fetch_google_api_token_simple(client_code=client_code)

    # STEP 1: FETCH KEYWORDS
    async def fetch_keywords(self) -> list:
        """Fetch all active non-removed keywords for the campaign (async)."""
        try:
            endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "developer-token": self.developer_token,
                "login-customer-id": self.login_customer_id,
                "Content-Type": "application/json",
            }

            duration_clause = format_duration_clause(self.duration)
            query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.negative,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_micros,
                metrics.conversions,
                segments.date
            FROM keyword_view
            WHERE campaign.id = {self.campaign_id}
            AND segments.date {duration_clause}
            AND ad_group_criterion.status = 'ENABLED'
            ORDER BY ad_group.id, segments.date
            """
            async with httpx.AsyncClient() as client:
                response = await client.post(endpoint, headers=headers, json={"query": query})

            data = response.json()
            keywords = []

            def _safe_float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0.0

            def _safe_int(value):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return 0

            for row in data.get("results", []):
                metric = row.get("metrics", {})
                keyword_info = row.get("adGroupCriterion", {}).get("keyword", {})

                keyword_text = keyword_info.get("text")
                if keyword_text:
                    clicks = _safe_int(metric.get("clicks"))
                    conversions = _safe_float(metric.get("conversions"))

                    keywords.append({
                        "keyword": keyword_text,
                        "ad_group_id": row.get("adGroup", {}).get("id"),
                        "ad_group_name": row.get("adGroup", {}).get("name"),
                        "match_type": keyword_info.get("match_type"),
                        "quality_score": row.get("adGroupCriterion", {}).get("quality_info", {}).get("quality_score"),
                        "negative": row.get("adGroupCriterion", {}).get("negative"),
                        "impressions": _safe_int(metric.get("impressions")),
                        "clicks": clicks,
                        "ctr": _safe_float(metric.get("ctr")),
                        "average_cpc": _safe_float(metric.get("average_cpc")),
                        "cost_micros": _safe_int(metric.get("cost_micros")),
                        "conversions": conversions,
                        "date": row.get("segments", {}).get("date"),
                    })

            return keywords
        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            return []
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return []


    # STEP 2: FETCH SEARCH TERMS
    def fetch_search_terms(self, keywords: list) -> list:
        """Fetch all search terms for multiple keywords in one API call (with safe error handling)."""
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
                search_term_view.ad_group,
                search_term_view.resource_name,
                search_term_view.search_term,
                search_term_view.status,
                segments.keyword.info.text,
                segments.search_term_match_type,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_per_conversion,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_micros,
                metrics.conversions
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
                search_view = row.get("searchTermView", {})
                metrics = row.get("metrics", {})
                segments = row.get("segments", {})

                term = search_view.get("searchTerm")
                status = (search_view.get("status") or "").strip().upper()
                keyword_text = segments.get("keyword", {}).get("info", {}).get("text")
                ad_group_id = row.get("adGroup", {}).get("resourceName")
                # match_type = segments.get("search_term_match_type")
                match_type = (
                segments.get("searchTermMatchType")
                or segments.get("search_term_match_type")
                or segments.get("searchterm_match_type")
            )

                if status in ["EXCLUDED", "ADDED_EXCLUDED", "ADDED"]:
                    continue

                raw_cost = metrics.get("costPerConversion") or metrics.get("cost_per_conversion")
                if raw_cost is None:
                    continue

                search_terms.append({
                    "searchterm": term,
                    "keyword": keyword_text,
                    "status": status,
                    "adGroupId": ad_group_id,
                    "matchType": match_type,
                    "metrics": {
                        "impressions": _safe_int(metrics.get("impressions")),
                        "clicks": _safe_int(metrics.get("clicks")),
                        "ctr": _safe_float(metrics.get("ctr")),
                        "conversions": _safe_float(metrics.get("conversions")),
                        "costMicros": _safe_int(metrics.get("costMicros") or metrics.get("cost_micros")),
                        "averageCpc": _safe_float(metrics.get("averageCpc") or metrics.get("average_cpc")),
                        "costPerConversion": _safe_float(raw_cost),
                    },
                })

            return search_terms

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e} - {response.text if 'response' in locals() else ''}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return []
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON response.")
            return []
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return []


    # STEP 3: RUN PIPELINE
    async def run_pipeline(self) -> list:
        """Full flow: fetch keywords → fetch search terms → classify."""
        logger.info("Running full search term analysis pipeline...")

        keywords = await self.fetch_keywords()
        if not keywords:
            logger.warning("No keywords found — skipping search term fetch.")
            return []

        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            logger.warning("No search terms found — skipping classification.")
            return []

        classified_terms = await analyze_search_term_performance(search_terms)
        return classified_terms