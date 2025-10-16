

import os
import requests
from datetime import datetime
from services.search_term_analyzer import classify_search_terms


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

    # STEP 1: FETCH KEYWORDS
    def fetch_keywords(self) -> list:
        """Fetch all active non-negative keywords for the campaign."""
        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "content-type": "application/json",
        }

        query = f"""
        SELECT
            ad_group_criterion.criterion_id,
            ad_group_criterion.keyword.text,
            ad_group_criterion.negative,
            campaign.id
        FROM ad_group_criterion
        WHERE ad_group_criterion.type = 'KEYWORD'
          AND ad_group_criterion.negative = FALSE
          AND campaign.id = {self.campaign_id}
        """

        response = requests.post(endpoint, headers=headers, json={"query": query})
        if not response.ok:
            print("[ERROR] Failed to fetch keywords.")
            return []

        data = response.json()
        keywords = []
        for row in data.get("results", []):
            keyword_text = (
                row.get("adGroupCriterion", {}).get("keyword", {}).get("text")
            )
            if keyword_text:
                keywords.append(keyword_text)

        return keywords

    # STEP 2: FETCH SEARCH TERMS
    def fetch_search_terms(self, keywords: list) -> list:
        """Fetch all search terms for multiple keywords in one API call."""
        print("[INFO] Fetching search terms...")

        if not keywords:
            print("[WARN] No keywords provided.")
            return []

        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "content-type": "application/json",
        }

        duration_clause = self._format_duration_clause(self.duration)
        sanitized_keywords = [kw.replace("'", "\\'") for kw in keywords]
        keyword_list = "', '".join(sanitized_keywords)
        in_clause = f"('{keyword_list}')"

        query = f"""SELECT search_term_view.ad_group, search_term_view.resource_name, search_term_view.search_term, search_term_view.status, segments.keyword.info.text, segments.search_term_match_type, metrics.impressions, metrics.clicks, metrics.cost_per_conversion, metrics.ctr, metrics.average_cpc, metrics.cost_micros, metrics.conversions FROM search_term_view WHERE campaign.id = {self.campaign_id} AND segments.date {duration_clause} AND segments.keyword.info.text IN {in_clause}
        """

        response = requests.post(endpoint, headers=headers, json={"query": query})
        data = response.json()
        
        if not response.ok:
            print("[ERROR] Failed to fetch search terms.")
            return []

        search_terms = []
        for row in data.get("results", []):
            search_view = row.get("searchTermView", {})
            metrics = row.get("metrics", {})
            segments = row.get("segments", {})

            term = search_view.get("searchTerm")
            status = (search_view.get("status") or "").strip().upper()
            keyword_text = (
                segments.get("keyword", {})
                .get("info", {})
                .get("text")
            )

            #Skip terms that are ADDED, EXCLUDED, or ADDED_EXCLUDED
            if status in ["EXCLUDED", "ADDED_EXCLUDED", "ADDED"]:
                continue

            # Skip if missing conversion cost
            raw_cost = metrics.get("costPerConversion") or metrics.get("cost_per_conversion")
            if raw_cost is None:
                continue

            search_terms.append({
                "searchterm": term,
                "keyword": keyword_text,
                "status": status,
                "metrics": {
                    "impressions": metrics.get("impressions"),
                    "clicks": metrics.get("clicks"),
                    "ctr": metrics.get("ctr"),
                    "conversions": metrics.get("conversions"),
                    "costMicros": metrics.get("costMicros"),
                    "averageCpc": metrics.get("averageCpc"),
                    "costPerConversion": metrics.get("costPerConversion"),
                },
            })

        return search_terms

    def _format_duration_clause(self, duration: str) -> str:
        """Convert duration text or range into SQL-compatible clause."""
        if "," in duration:
            start_raw, end_raw = [d.strip() for d in duration.split(",")]

            def normalize(d):
                if "/" in d:
                    return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
                elif "-" in d:
                    return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d")
                return d

            start_date = normalize(start_raw)
            end_date = normalize(end_raw)
            return f"BETWEEN '{start_date}' AND '{end_date}'"
        else:
            return duration

    # STEP 3: CLASSIFY SEARCH TERMS (Metric-based)
    async def classify_search_terms(self, search_terms: list) -> list:
        """Classify search terms using cost-per-conversion rule."""
        print("[INFO] Classifying search terms (cost_per_conversion-based)...")
        return await classify_search_terms(search_terms)

    # STEP 4: RUN PIPELINE
    async def run_pipeline(self) -> list:
        """Full flow: fetch keywords → fetch search terms → classify."""
        print("[INFO] Running full search term analysis pipeline...")

        keywords = self.fetch_keywords()
        if not keywords:
            print("[WARN] No keywords found — skipping search term fetch.")
            return []

        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            print("[WARN] No search terms found — skipping classification.")
            return []

        classified_terms = await self.classify_search_terms(search_terms)
        return classified_terms












