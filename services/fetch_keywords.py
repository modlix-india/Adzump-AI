import os
import requests
import asyncio
import json
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

    # -------------------------------------------------------------------------
    # STEP 1: FETCH KEYWORDS
    # -------------------------------------------------------------------------
    def fetch_keywords(self) -> list:
        """Fetch all active non-negative keywords for the campaign."""
        print(f"[INFO] Fetching keywords for campaign {self.campaign_id}")

        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "content-type": "application/json",
        }

        query = f""" SELECT ad_group_criterion.resource_name, ad_group_criterion.criterion_id, ad_group_criterion.type, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group_criterion.status, ad_group_criterion.negative, ad_group.name, ad_group.id, campaign.name, campaign.id FROM ad_group_criterion WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE AND campaign.id = {self.campaign_id}
        """

        response = requests.post(endpoint, headers=headers, json={"query": query})
        if not response.ok:
            print("[ERROR] Failed to fetch keywords")
            print(response.text)
            return []

        data = response.json()
        streams = data if isinstance(data, list) else [data]
        keywords = []

        for stream in streams:
            for row in stream.get("results", []):
                ad_group_criterion = row.get("adGroupCriterion", {})
                keyword_info = ad_group_criterion.get("keyword", {})
                keyword_text = keyword_info.get("text")
                if keyword_text:
                    keywords.append(keyword_text)

        print(f"[INFO] ✅ Extracted {len(keywords)} keywords: {keywords}")
        return keywords

    # -------------------------------------------------------------------------
    # STEP 2: FETCH SEARCH TERMS
    # -------------------------------------------------------------------------
    def fetch_search_terms(self, keywords: list) -> list:
        """Fetch all search terms for multiple keywords in a single Google Ads API call."""
        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "content-type": "application/json",
        }

        all_search_terms = []

        # ✅ Inline date formatting logic
        duration = self.duration
        if "," in duration:
            start_raw, end_raw = [d.strip() for d in duration.split(",")]

            def normalize(d):
                # Converts both DD/MM/YYYY and YYYY-MM-DD → YYYY-MM-DD
                if "/" in d:
                    return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
                elif "-" in d:
                    return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d")
                return d

            start_date = normalize(start_raw)
            end_date = normalize(end_raw)
            duration_clause = f"BETWEEN '{start_date}' AND '{end_date}'"
        else:
            duration_clause = duration

        print(f"[INFO] Fetching search terms for {len(keywords)} keywords in one query...")
        print(f"[INFO] Date range applied: {duration_clause}")

        sanitized_keywords = [kw.replace('"', '\\"').replace("'", "\\'") for kw in keywords]
        keyword_list = "', '".join(sanitized_keywords)
        in_clause = f"('{keyword_list}')"

        # ✅ Google Ads GAQL query
        query = f"""SELECT search_term_view.ad_group, search_term_view.resource_name, search_term_view.search_term, search_term_view.status, segments.keyword.info.text, segments.search_term_match_type,metrics.impressions, metrics.clicks, metrics.cost_per_conversion, metrics.ctr, metrics.average_cpc,metrics.cost_micros, metrics.conversions, metrics.cost_per_conversion FROM search_term_view WHERE campaign.id = {self.campaign_id} AND segments.date {duration_clause} AND segments.keyword.info.text IN {in_clause}
        """

        print(f"\n[DEBUG] Final GAQL query:\n{query}")

        response = requests.post(endpoint, headers=headers, json={"query": query})
        print("response: ",response.json())
        # if not response.ok:
        #     print("[ERROR] Failed fetching search terms.")
        #     print(json.dumps(response.json(), indent=2))
        #     return []

        data = response.json()
        streams = data if isinstance(data, list) else [data]
        for stream in streams:
            for row in stream.get("results", []):
                term = row.get("searchTermView", {}).get("searchTerm")
                # keyword = row.get("segments", {}).get("keyword", {}).get("info", {}).get("text")
                metrics = row.get("metrics", {})

                # if not term or not keyword:
                #     continue

                all_search_terms.append({
                    "searchterm": term,
                    # "keyword": keyword,
                    "metrics": {
                        "costPerConversion": metrics.get("costPerConversion"),
                    }
                })

        print(f"\n[INFO] ✅ Extracted {len(all_search_terms)} search terms.\n")
        return all_search_terms

    # -------------------------------------------------------------------------
    # STEP 3: CLASSIFY SEARCH TERMS
    # -------------------------------------------------------------------------
    async def classify_search_terms(self, search_terms: list) -> list:
        """Classify search terms using the LLM-based analyzer."""
        print("[INFO] Classifying search terms via LLM...")
        return await classify_search_terms(search_terms)

    # -------------------------------------------------------------------------
    # STEP 4: RUN PIPELINE
    # -------------------------------------------------------------------------
    async def run_pipeline(self) -> list:
        """Full flow: fetch keywords → fetch search terms → classify."""
        print(f"[INFO] Running search term pipeline for campaign {self.campaign_id}...")
        keywords = self.fetch_keywords()
        if not keywords:
            print("[WARN] No keywords found — skipping search term fetch.")
            return []

        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            print("[WARN] No search terms found — skipping classification.")
            return []

        classified_terms = await self.classify_search_terms(search_terms)
        print(f"[INFO] ✅ Pipeline complete — classified {len(classified_terms)} search terms.\n")
        return classified_terms





# working fine for the fetching kkeywords and constucting payload foe search terms


# import os
# import requests
# import asyncio
# import json
# from datetime import datetime
# from services.search_term_analyzer import classify_search_terms

# class SearchTermPipeline:
#     def __init__(
#         self,
#         client_code: str,
#         customer_id: str,
#         login_customer_id: str,
#         campaign_id: str,
#         duration: str,
#     ):
#         """
#         duration can be either:
#           - 'LAST_30_DAYS', 'LAST_7_DAYS', etc.
#           - '01/01/2025,31/12/2025' (custom range in DD/MM/YYYY format)
#         """
#         self.client_code = client_code
#         self.customer_id = customer_id
#         self.login_customer_id = login_customer_id
#         self.campaign_id = campaign_id
#         self.duration = duration.strip()
#         self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
#         self.access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

    
#     # STEP 1: FETCH KEYWORDS
    
#     def fetch_keywords(self) -> list:
#         """Fetch all active non-negative keywords for the campaign."""
#         print(f"[INFO] Fetching keywords for campaign {self.campaign_id}")

#         endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"

#         headers = {
#             "authorization": f"Bearer {self.access_token}",
#             "developer-token": self.developer_token,
#             "login-customer-id": self.login_customer_id,
#             "content-type": "application/json",
#         }

#         query = f"""SELECT ad_group_criterion.resource_name, ad_group_criterion.criterion_id, ad_group_criterion.type, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,ad_group_criterion.status,ad_group_criterion.negative, ad_group.name, ad_group.id, campaign.name, campaign.id FROM ad_group_criterion WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE AND campaign.id = {self.campaign_id}"""
#         print(endpoint, headers)
#         response = requests.post(endpoint, headers=headers, json={"query": query})
#         print(response.json())
#         # if not response.ok:
#         #     print("[ERROR] Failed to fetch keywords")
#         #     print(response.text)
#         #     return []

#         data = response.json()
#         streams = data if isinstance(data, list) else [data]
#         keywords = []

#         for stream in streams:
#             for row in stream.get("results", []):
#                 # Notice the camelCase keys
#                 ad_group_criterion = row.get("adGroupCriterion", {})
#                 keyword_info = ad_group_criterion.get("keyword", {})

#                 keyword_text = keyword_info.get("text")
#                 if keyword_text:
#                     keywords.append(keyword_text)

#         print(f"[INFO] Extracted {len(keywords)} keywords: {keywords}")
#         return keywords

#     def fetch_search_terms(self, keywords: list) -> list:
#         """Fetch all search terms for multiple keywords in a single Google Ads API call."""
#         endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:searchStream"
#         headers = {
#             "authorization": f"Bearer {self.access_token}",
#             "developer-token": self.developer_token,
#             "login-customer-id": self.login_customer_id,
#             "content-type": "application/json",
#         }

#         all_search_terms = []

#         # ✅ Inline date formatting logic
#         duration = self.duration
#         if "," in duration:
#             start_raw, end_raw = [d.strip() for d in duration.split(",")]

#             def normalize(d):
#                 # Converts both DD/MM/YYYY and YYYY/MM/DD → YYYY-MM-DD
#                 if "/" in d:
#                     return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
#                 elif "-" in d:
#                     return datetime.strptime(d, "%Y-%m-%d").strftime("%Y-%m-%d")
#                 return d

#             start_date = normalize(start_raw)
#             end_date = normalize(end_raw)
#             duration_clause = f"BETWEEN '{start_date}' AND '{end_date}'"
#         else:
#             duration_clause = duration

#         print(f"[INFO] Fetching search terms for {len(keywords)} keywords in one query...")
#         print(f"[INFO] Date range applied: {duration_clause}")

#         # ✅ Sanitize and quote keywords properly
#         sanitized_keywords = [kw.replace('"', '\\"').replace("'", "\\'") for kw in keywords]
#         keyword_list = "', '".join(sanitized_keywords)
#         in_clause = f"('{keyword_list}')"

#         # ✅ EXACT query structure as in your Map([...]) version
#         query = f""" SELECT search_term_view.ad_group, search_term_view.resource_name, search_term_view.search_term, search_term_view.status, segments.keyword.info.text, segments.search_term_match_type, metrics.impressions, metrics.clicks, metrics.cost_per_conversion, metrics.ctr, metrics.average_cpc, metrics.cost_micros, metrics.conversions FROM search_term_view WHERE campaign.id = {self.campaign_id} AND segments.keyword.info.text IN {in_clause} AND segments.date {duration_clause}
#         """
#         print(f"\n[DEBUG] Final GAQL query:\n{query}")

#         # ✅ API request
#         response = requests.post(endpoint, headers=headers, json={"query": query})

#         if not response.ok:
#             print("[ERROR] Failed fetching search terms.")
#             print(json.dumps(response.json(), indent=2))
#             return []

#         try:
#             data = response.json()
#         except Exception as e:
#             print(f"[ERROR] Failed to parse response JSON: {e}")
#             return []

#         streams = data if isinstance(data, list) else [data]
#         for stream in streams:
#             for row in stream.get("results", []):
#                 term = row.get("search_term_view", {}).get("search_term")
#                 keyword = row.get("segments", {}).get("keyword", {}).get("info", {}).get("text")
#                 metrics = row.get("metrics", {})

#                 if not term or not keyword:
#                     continue

#                 all_search_terms.append({
#                     "searchterm": term,
#                     "keyword": keyword,
#                     "metrics": {
#                         "impressions": metrics.get("impressions"),
#                         "clicks": metrics.get("clicks"),
#                         "ctr": metrics.get("ctr"),
#                         "averageCpc": metrics.get("average_cpc"),
#                         "conversions": metrics.get("conversions"),
#                         "costMicros": metrics.get("cost_micros"),
#                         "costPerConversion": metrics.get("cost_per_conversion"),
#                     }
#                 })

#         print(f"\n[INFO] ✅ Extracted {len(all_search_terms)} search terms.\n")
#         return all_search_terms

   
#     # # -------------------------------------------------------------------------
#     # # STEP 3: CLASSIFY SEARCH TERMS
#     # # -------------------------------------------------------------------------
#     # async def classify_search_terms(self, search_terms: list) -> list:
#     #     """Classify search terms using LLM."""
#     #     print("[INFO] Classifying search terms...")
#     #     return await classify_search_terms(search_terms)

#     # # -------------------------------------------------------------------------
#     # # STEP 4: RUN PIPELINE
#     # # -------------------------------------------------------------------------
#     async def run_pipeline(self) -> list:
#         """Full flow: fetch keywords → fetch search terms → classify."""
#         print(f"[INFO] Running search term pipeline for campaign {self.campaign_id}...")
#         keywords = self.fetch_keywords()
#         if not keywords:
#             print("[WARN] No keywords found — skipping search term fetch.")
#             return []
#         search_terms = self.fetch_search_terms(keywords)
#         print("searchterms", search_terms)
#         classified_terms = await self.classify_search_terms(search_terms)
#         print(f"[INFO] ✅ Pipeline complete — classified {len(classified_terms)} search terms.\n")
#         return classified_terms





# prevoius version

# import os
# import requests
# import asyncio
# import json
# from services.search_term_analyzer import classify_search_terms


# class SearchTermPipeline:
#     def __init__(self, client_code: str, customer_id: str, login_customer_id: str, campaign_id: str):
#         self.client_code = client_code
#         self.customer_id = customer_id
#         self.login_customer_id = login_customer_id
#         self.campaign_id = campaign_id
#         self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
#         self.access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN")

#     # -------------------------------------------------------------------------
#     # STEP 1: FETCH KEYWORDS
#     # -------------------------------------------------------------------------
#     def fetch_keywords(self) -> list:
#         """Fetch all keywords for the campaign (with debug logging)."""
#         endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
#         headers = {
#             "authorization": f"Bearer {self.access_token}",
#             "developer-token": self.developer_token,
#             "login-customer-id": self.login_customer_id,
#             "content-type": "application/json",
#         }

#         query = f"""
#             SELECT ad_group_criterion.keyword.text
#             FROM ad_group_criterion
#             WHERE campaign.id = {self.campaign_id}
#               AND ad_group_criterion.type = 'KEYWORD'
#         """

#         print(f"[INFO] Fetching keywords for campaign {self.campaign_id}...")

#         response = requests.post(endpoint, headers=headers, json={"query": query})

#         try:
#             response.raise_for_status()
#         except requests.HTTPError as e:
#             print("[ERROR] Google Ads API returned an HTTP error:")
#             print(response.text)
#             raise e

#         # Parse JSON safely
#         try:
#             data = response.json()
#         except Exception:
#             print("[ERROR] Could not decode JSON:")
#             print(response.text)
#             raise

#         # 🔍 Print the entire API response for debugging
#         print("\n[DEBUG] Google Ads API raw response (keywords):")
#         print(json.dumps(data, indent=2))

#         keywords = []

#         # Validate structure
#         if "results" not in data:
#             print("[WARN] No 'results' field found in response. Top-level keys:", list(data.keys()))

#         for row in data.get("results", []):
#             ad_group_criterion = row.get("ad_group_criterion")
#             if not ad_group_criterion:
#                 print("[WARN] Missing 'ad_group_criterion' in row:")
#                 print(json.dumps(row, indent=2))
#                 continue

#             keyword_info = ad_group_criterion.get("keyword")
#             if not keyword_info:
#                 print("[WARN] Missing 'keyword' in row:")
#                 print(json.dumps(row, indent=2))
#                 continue

#             keyword_text = keyword_info.get("text")
#             if keyword_text:
#                 keywords.append(keyword_text)

#         print(f"[INFO] Extracted {len(keywords)} keywords.\n")
#         return keywords

#     # -------------------------------------------------------------------------
#     # STEP 2: FETCH SEARCH TERMS FOR EACH KEYWORD
#     # -------------------------------------------------------------------------
#     def fetch_search_terms(self, keywords: list) -> list:
#         """Fetch search terms for a list of keywords."""
#         endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:searchStream"
#         headers = {
#             "authorization": f"Bearer {self.access_token}",
#             "developer-token": self.developer_token,
#             "login-customer-id": self.login_customer_id,
#             "content-type": "application/json",
#         }

#         all_search_terms = []
#         print(f"[INFO] Fetching search terms for {len(keywords)} keywords...")

#         for keyword in keywords:
#             query = f"""
#                 SELECT
#                   search_term_view.search_term,
#                   metrics.impressions,
#                   metrics.clicks,
#                   metrics.ctr,
#                   metrics.average_cpc,
#                   metrics.conversions,
#                   metrics.cost_micros
#                 FROM search_term_view
#                 WHERE campaign.id = {self.campaign_id}
#                   AND ad_group_criterion.keyword.text = "{keyword.replace('"', '\\"')}"
#             """

#             response = requests.post(endpoint, headers=headers, json={"query": query})

#             try:
#                 response.raise_for_status()
#             except requests.HTTPError as e:
#                 print(f"[ERROR] Failed fetching search terms for keyword '{keyword}':")
#                 print(response.text)
#                 continue  # skip this keyword

#             try:
#                 data = response.json()
#             except Exception:
#                 print(f"[ERROR] Could not parse JSON for keyword '{keyword}':")
#                 print(response.text)
#                 continue

#             # 🔍 Debug print for this keyword
#             print(f"\n[DEBUG] Raw search term response for keyword '{keyword}':")
#             print(json.dumps(data, indent=2))

#             # Handle both searchStream (list) and search (dict)
#             if isinstance(data, list):
#                 streams = data
#             else:
#                 streams = [data]

#             for stream in streams:
#                 for row in stream.get("results", []):
#                     term = row.get("search_term_view", {}).get("search_term")
#                     metrics = row.get("metrics", {})

#                     if not term:
#                         continue

#                     all_search_terms.append({
#                         "searchterm": term,
#                         "keyword": keyword,
#                         "metrics": {
#                             "impressions": metrics.get("impressions"),
#                             "clicks": metrics.get("clicks"),
#                             "ctr": metrics.get("ctr"),
#                             "averageCpc": metrics.get("average_cpc"),
#                             "conversions": metrics.get("conversions"),
#                             "costMicros": metrics.get("cost_micros"),
#                             "costPerConversion": (
#                                 metrics.get("cost_micros") / metrics.get("conversions")
#                                 if metrics.get("conversions") not in (None, 0)
#                                 else None
#                             ),
#                         }
#                     })

#         print(f"[INFO] Extracted {len(all_search_terms)} search terms.\n")
#         return all_search_terms

#     # -------------------------------------------------------------------------
#     # STEP 3: CLASSIFY SEARCH TERMS
#     # -------------------------------------------------------------------------
#     async def classify_search_terms(self, search_terms: list) -> list:
#         """Classify search terms using LLM (via search_term_analyzer)."""
#         print("[INFO] Classifying search terms using LLM...")
#         return await classify_search_terms(search_terms)

#     # -------------------------------------------------------------------------
#     # STEP 4: FULL PIPELINE
#     # -------------------------------------------------------------------------
#     async def run_pipeline(self) -> list:
#         """
#         Full end-to-end pipeline:
#           1. Fetch keywords dynamically
#           2. Fetch search terms for those keywords
#           3. Classify search terms using LLM
#         Returns a list of classified search terms with recommendations & reasons.
#         """
#         print(f"[INFO] Running full search term pipeline for campaign {self.campaign_id}...")
#         keywords = self.fetch_keywords()
#         search_terms = self.fetch_search_terms(keywords)
#         classified_terms = await self.classify_search_terms(search_terms)
#         print(f"[INFO] Pipeline complete — classified {len(classified_terms)} search terms.\n")
#         return classified_terms
