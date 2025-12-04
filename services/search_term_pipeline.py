import os
import json
import logging
import requests
from third_party.google.services import ads_service, keywords_service
from services.search_term_analyzer import analyze_search_term_performance
from services.openai_client import chat_completion
import utils.date_utils as date_utils
from oserver.services.connection import fetch_google_api_token_simple
import asyncio

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def load_search_term_prompt(file_name: str) -> str:
    """
    Loads search-term-specific prompts from:
    prompts/search_term/{file_name}
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(root_dir, "prompts", "search_term", file_name)

    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()

class SearchTermPipeline:
    """Pipeline to evaluate brand, configuration, and overall search term relevancy."""
    OPENAI_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        client_code: str,
        customer_id: str,
        login_customer_id: str,
        campaign_id: str,
        duration: str,
        access_token: str,
    ):
        self.client_code = client_code
        self.customer_id = customer_id
        self.login_customer_id = login_customer_id
        self.campaign_id = campaign_id
        self.duration = duration.strip()
        self.access_token = access_token
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        self.google_ads_access_token = fetch_google_api_token_simple(client_code=client_code)

    # Internal helper for LLM call

    async def _call_llm(self, system_msg: str, user_msg: str, label: str):
        """Send structured prompts to the OpenAI chat model and handle errors."""
        try:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]
            response = await chat_completion(messages, model=self.OPENAI_MODEL)
            content = response.choices[0].message.content.strip() if response.choices else ""

            logger.info(f"[LLM] {label} relevance check completed.")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"[LLM] {label} returned non-JSON response: {content[:200]}...")
                return {"raw_response": content}

        except Exception as e:
            logger.error(f"[LLM] {label} relevance check failed: {e}")
            return {"error": str(e)}

    # Configuration Relevance
    async def check_configuration_relevance(self, summary: str, search_term: str) -> dict:
        """Check if search term refers to configurations (1BHK, villa, etc.)."""
        system_msg = load_search_term_prompt("configuration_relevancy_prompt.txt")

        user_msg = (
            f"PROJECT SUMMARY:\n{summary}\n\nSEARCH TERM:\n{search_term}"
        )
        return await self._call_llm(system_msg, user_msg, "configuration")

    # Brand Relevance
    async def check_brand_relevance(self, summary: str, search_term: str) -> dict:
        """Check if search term refers to brand, competitor, or generic."""
        system_msg = load_search_term_prompt("brand_relevancy_prompt.txt")
        user_msg = (
            f"PROJECT SUMMARY:\n{summary}\n\nSEARCH TERM:\n{search_term}"
        )
        return await self._call_llm(system_msg, user_msg, "brand")

    #Location Relevance
    async def check_location_relevance(self, summary: str, search_term: str, brand_type: dict):
        """
        Evaluates the location relevancy for a search term based on brand type.

        - If brand.type == 'competitor': skips LLM call and returns 'skipped_due_to_competitor'.
        - If brand.type in ['own_brand', 'generic']: calls LLM to evaluate location relevancy.
        - If brand.type missing or invalid: returns 'no_brand_context'.
        """

        # Competitor case — skip LLM
        if brand_type == "competitor":
            return {
                "location": {
                    "match": False,
                    "type": "skipped_due_to_competitor",
                    "score": 0.0,
                    "match_level": "No Match",
                    "reason": "Search term contains a competitor brand, so location relevancy check was skipped."
                }
            }

        # Own brand or generic — perform LLM call
        if brand_type in ("own_brand", "generic"):
            system_msg = load_search_term_prompt("location_relevancy_prompt.txt")
            user_msg = f"PROJECT SUMMARY:\n{summary}\n\nSEARCH TERM:\n{search_term}"

            try:
                llm_response = await self._call_llm(system_msg, user_msg, "location")
                return llm_response
            except Exception as e:
                return {
                    "location": {
                        "match": False,
                        "type": "llm_error",
                        "score": 0.0,
                        "match_level": "No Match",
                        "reason": f"Error during LLM evaluation: {str(e)}"
                    }
                }

        # Unknown brand context — skip
        return {
            "location": {
                "match": False,
                "type": "no_brand_context",
                "score": 0.0,
                "match_level": "No Match",
                "reason": (
                    "Brand type was not identified (missing or invalid), "
                    "so location relevance check was skipped."
                )
            }
        }

    # Overall Relevance
    async def check_overall_relevance(
        self,
        summary: str,
        search_term: str,
        brand_result: dict,
        config_result: dict,
        location_result: dict
    ) -> dict:
        """Combine brand, configuration, and location results and summarize overall intent.
    Ensures consistent output structure: overallPerformance -> overall"""
        system_msg = load_search_term_prompt("overall_relevancy_prompt.txt")
        user_msg = (
            f"PROJECT SUMMARY:\n{summary}\n\n"
            f"SEARCH TERM:\n{search_term}\n\n"
            f"BRAND RELEVANCE RESULT:\n{json.dumps(brand_result, indent=2)}\n\n"
            f"CONFIGURATION RELEVANCE RESULT:\n{json.dumps(config_result, indent=2)}"
            f"LOCATION RELEVANCE RESULT:\n{json.dumps(location_result, indent=2)}"

        )
        return await self._call_llm(system_msg, user_msg, "overall")

    # Google Ads Search Term Fetch
    def fetch_search_terms(self, keywords: list) -> list:
        """Fetch all search terms for multiple keywords in one API call."""
        logger.info("Fetching search terms...")

        if not keywords:
            logger.warning("No keywords provided.")
            return []

        endpoint = f"https://googleads.googleapis.com/v20/customers/{self.customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {self.google_ads_access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "Content-Type": "application/json",
        }

        try:
            duration_clause = date_utils.format_duration_clause(self.duration)
            keyword_texts = [kw.keyword for kw in keywords if kw.keyword]
            keyword_list = "', '".join(keyword_texts)
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
                AND ad_group.status = 'ENABLED'
                AND campaign.status = 'ENABLED'
            ORDER BY ad_group.id
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
                ad_group = row.get("adGroup", {})

                term = search_view.get("searchTerm")
                keyword_text = segments.get("keyword", {}).get("info", {}).get("text")
                match_type = segments.get("searchTermMatchType")

                if not term or not keyword_text:
                    continue

                search_terms.append({
                    "searchterm": term,
                    "status": search_view.get("status"),
                    "keyword": keyword_text,
                    "matchType": match_type,
                    "adGroupId": ad_group.get("resourceName"),
                    "metrics": {
                        "impressions": metrics.get("impressions", 0) or 0,
                        "clicks": metrics.get("clicks", 0) or 0,
                        "ctr": metrics.get("ctr", 0) or 0,
                        "conversions": metrics.get("conversions", 0) or 0,
                        "costMicros": int(metrics.get("costMicros", 0) or 0),
                        "averageCpc": metrics.get("averageCpc", 0) or 0,
                        "cost": (int(metrics.get("costMicros", 0) or 0)) / 1_000_000,
                        "costPerConversion": metrics.get("costPerConversion", 0) or 0,
                    },
                })

            return search_terms

        except Exception as e:
            logger.exception(f"Error fetching search terms: {e}")
            return []

    # Full Pipeline
    import asyncio  # <--- needed for concurrency

    async def run_pipeline(self) -> dict:
        """Full flow: fetch ads, keywords, search terms → analyze + LLM relevance with concurrency."""
        logger.info("Running full search term analysis pipeline...")

        # Fetch ads summary
        ads_data = await ads_service.fetch_ads(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            access_token=self.access_token,
        )
        summary = ads_data.get("summary") if isinstance(ads_data, dict) else ""

        # Fetch keywords
        keywords = await keywords_service.fetch_keywords(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            duration=self.duration,
        )
        if not keywords:
            logger.warning("No keywords found — skipping search term fetch.")
            return {"classified_search_terms": []}

        # Fetch search terms
        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            logger.warning("No search terms found — skipping classification.")
            return {"classified_search_terms": []}

        # Analyze metrics
        classified_terms = await analyze_search_term_performance(search_terms)

        async def process_term(term_data):
            search_term = term_data["term"]
            performances = term_data.pop("performances", {})

            if "classification" in term_data or "recommendation" in term_data:
                performances["cpc"] = {
                    "classification": term_data.pop("classification", None),
                    "recommendation": term_data.pop("recommendation", None),
                }

            # Run LLM calls concurrently
            config_task = self.check_configuration_relevance(summary, search_term)
            brand_task = self.check_brand_relevance(summary, search_term)
            # We need brand type for location, so wait for brand first
            brand_eval = await brand_task
            brand_type = brand_eval.get("brand", {}).get("type", None)

            location_task = self.check_location_relevance(summary, search_term, brand_type)

            # Wait for configuration + location concurrently
            config_eval, location_eval = await asyncio.gather(config_task, location_task)

            brand_match = brand_eval.get("brand", {}).get("match", False)
            config_match = config_eval.get("configuration", {}).get("match", False)

            # Overall classification
            if not brand_match and not config_match:
                summary_eval = {
                    "overall": {
                        "match": False,
                        "match_level": "No Match",
                        "intent_stage": "Irrelevant",
                        "suggestion_type": "negative",
                        "reason": "No brand, configuration, or location match found — search term is unrelated to the project."
                    }
                }
            else:
                summary_eval = await self.check_overall_relevance(
                    summary, search_term, brand_eval, config_eval, location_eval
                )

            # Merge all evaluations
            term_data["evaluations"] = {
                "performances": performances,
                "relevancyCheck": {
                    "brandRelevancy": brand_eval,
                    "configurationRelevancy": config_eval,
                    "locationRelevancy": location_eval
                },
                "overallPerformance": summary_eval,
            }

            return term_data
        # Process all terms concurrently
        classified_terms = await asyncio.gather(*(process_term(td) for td in classified_terms))
        logger.info("Search term pipeline completed successfully.")
        return {"classified_search_terms": classified_terms}