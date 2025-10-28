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
        self.access_token = fetch_google_api_token_simple(client_code=client_code)

    # STEP 1: FETCH KEYWORDS
    async def fetch_keywords(self) -> list:
        """Fetch all active keywords for the campaign (async),
        merge keyword_view (with metrics) + ad_group_criterion (all keywords).
        Ensures all keywords appear, metrics default to 0 if missing.
        """
        try:
            import httpx

            endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "developer-token": self.developer_token,
                "login-customer-id": self.login_customer_id,
                "Content-Type": "application/json",
            }

            duration_clause = format_duration_clause(self.duration)

           # Fetch from keyword_view 

            keyword_view_query = f"""
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
            AND ad_group_criterion.negative = FALSE
            ORDER BY ad_group.id, segments.date
            """

            async with httpx.AsyncClient() as client:
                kw_response = await client.post(endpoint, headers=headers, json={"query": keyword_view_query})
            kw_data = kw_response.json().get("results", [])
            logger.info(f"Keyword View returned {len(kw_data)} rows")

            # Fetch from ad_group_criterion (all keywords)

            ad_group_criterion_query = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.status,
                ad_group_criterion.negative
            FROM ad_group_criterion
            WHERE ad_group_criterion.type = 'KEYWORD'
            AND ad_group_criterion.status = 'ENABLED'
            AND campaign.id = {self.campaign_id}
            AND ad_group.status = 'ENABLED'
            AND ad_group_criterion.negative = FALSE
            """

            async with httpx.AsyncClient() as client:
                crit_response = await client.post(endpoint, headers=headers, json={"query": ad_group_criterion_query})
            crit_data = crit_response.json().get("results", [])
            logger.info(f" Ad Group Criterion returned {len(crit_data)} keywords")

            # Helper utilities

            def _safe_int(v):
                try: return int(float(v))
                except: return 0

            def _safe_float(v):
                try: return float(v)
                except: return 0.0

            def normalize(t: str) -> str:
                if not t:
                    return ""
                t = t.lower().strip()
                for ch in ["-", "_", "+", ".", ","]:
                    t = t.replace(ch, " ")
                return " ".join(t.split())

            # Aggregate Keyword View metrics

            kw_metrics = {}
            for row in kw_data:
                metric = row.get("metrics", {})
                keyword_info = row.get("adGroupCriterion", {}).get("keyword", {})
                ad_group = row.get("adGroup", {})

                text = normalize(keyword_info.get("text"))
                match_type = keyword_info.get("matchType")
                if not text or not match_type:
                    continue

                key = (text, match_type)
                if key not in kw_metrics:
                    kw_metrics[key] = {
                        "impressions": 0,
                        "clicks": 0,
                        "cost_micros": 0,
                        "conversions": 0.0,
                        "quality_score": row.get("adGroupCriterion", {}).get("qualityInfo", {}).get("qualityScore"),
                    }

                kw_metrics[key]["impressions"] += _safe_int(metric.get("impressions"))
                kw_metrics[key]["clicks"] += _safe_int(metric.get("clicks"))
                kw_metrics[key]["cost_micros"] += _safe_int(metric.get("costMicros"))
                kw_metrics[key]["conversions"] += _safe_float(metric.get("conversions"))

            # Merge both sources

            merged = []
            for row in crit_data:
                keyword_info = row.get("adGroupCriterion", {}).get("keyword", {})
                ad_group = row.get("adGroup", {})
                text = normalize(keyword_info.get("text"))
                match_type = keyword_info.get("matchType")
                if not text or not match_type:
                    continue

                key = (text, match_type)
                metrics = kw_metrics.get(key, {
                    "impressions": 0,
                    "clicks": 0,
                    "cost_micros": 0,
                    "conversions": 0.0,
                    "quality_score": None,
                })

                imp = metrics["impressions"]
                clk = metrics["clicks"]
                cost = metrics["cost_micros"]
                ctr = round((clk / imp) * 100, 2) if imp > 0 else 0.0
                avg_cpc = round((cost / clk / 1_000_000), 2) if clk > 0 else 0.0

                merged.append({
                    "keyword": keyword_info.get("text"),
                    "match_type": match_type,
                    "ad_group_id": ad_group.get("id"),
                    "ad_group_name": ad_group.get("name"),
                    "impressions": imp,
                    "clicks": clk,
                    "ctr": ctr,
                    "average_cpc": avg_cpc,
                    "cost_micros": cost,
                    "conversions": metrics["conversions"],
                    "quality_score": metrics["quality_score"],
                    "status": row.get("adGroupCriterion", {}).get("status"),
                    "negative": row.get("adGroupCriterion", {}).get("negative"),
                })

            logger.info(f"Final merged keyword count: {len(merged)}")
            count_with_metrics = sum(1 for x in merged if x["impressions"] > 0)
            logger.info(f"Keywords with metrics: {count_with_metrics}, without metrics: {len(merged) - count_with_metrics}")

            return merged

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