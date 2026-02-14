# TODO: Remove after trust in new search term optimization service (core/services/search_term_analyzer.py)
# TODO: Remove after trust in new search term optimization service (core/services/search_term_analyzer.py)
import os
import json
import asyncio
import httpx
from structlog import get_logger  # type: ignore

from third_party.google.services import ads_service
from structlog import get_logger  # type: ignore
import requests
from third_party.google.services import ads_service, keywords_service
from services.search_term_analyzer import analyze_search_term_performance
from services.openai_client import chat_completion
from utils import google_dateutils as date_utils
from oserver.services.connection import fetch_google_api_token_simple
from services.json_utils import safe_json_parse
from utils.google_dateutils import format_date_range
from utils.helpers import micros_to_rupees

logger = get_logger(__name__)


# Prompt loader
def load_search_term_prompt(file_name: str) -> str:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(root_dir, "prompts", "search_term", file_name)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()



# Pipeline
class SearchTermPipeline:
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
        self.google_ads_access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN") or fetch_google_api_token_simple(
            client_code=client_code
        )
        self.google_ads_access_token = os.getenv("GOOGLE_ADS_ACCESS_TOKEN") or fetch_google_api_token_simple(
            client_code=client_code
        )

    # LLM Caller (no silent failures)
    async def _call_llm(self, system_msg: str, user_msg: str, label: str) -> dict:
    # LLM Caller (no silent failures)
    async def _call_llm(self, system_msg: str, user_msg: str, label: str) -> dict:
        try:
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ]


            response = await chat_completion(messages, model=self.OPENAI_MODEL)
            content = (
                response.choices[0].message.content.strip() if response.choices else ""
            )

            parsed = safe_json_parse(content)

            if not parsed:
                logger.error("LLM JSON parsing failed", label=label)
                return {}

            return parsed
            content = (
                response.choices[0].message.content.strip() if response.choices else ""
            )

            parsed = safe_json_parse(content)

            if not parsed:
                logger.error("LLM JSON parsing failed", label=label)
                return {}

            return parsed

        except Exception as e:
            logger.exception("LLM call failed", label=label, error=str(e))
            return {}

    # Normalizers (schema enforcement)
    @staticmethod
    def normalize_brand(resp: dict) -> dict:
        if isinstance(resp, dict) and "brand" in resp:
            return resp

        return {
            "brand": {
                "match": False,
                "type": "generic",
                "competitor_detected": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    @staticmethod
    def normalize_configuration(resp: dict) -> dict:
        if isinstance(resp, dict) and "configuration" in resp:
            return resp

        return {
            "configuration": {
                "match": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    @staticmethod
    def normalize_location(resp: dict) -> dict:
        if isinstance(resp, dict) and "location" in resp:
            return resp

        return {
            "location": {
                "match": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    # Relevance checks
            logger.exception("LLM call failed", label=label, error=str(e))
            return {}

    # Normalizers (schema enforcement)
    @staticmethod
    def normalize_brand(resp: dict) -> dict:
        if isinstance(resp, dict) and "brand" in resp:
            return resp

        return {
            "brand": {
                "match": False,
                "type": "generic",
                "competitor_detected": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    @staticmethod
    def normalize_configuration(resp: dict) -> dict:
        if isinstance(resp, dict) and "configuration" in resp:
            return resp

        return {
            "configuration": {
                "match": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    @staticmethod
    def normalize_location(resp: dict) -> dict:
        if isinstance(resp, dict) and "location" in resp:
            return resp

        return {
            "location": {
                "match": False,
                "match_level": "No Match",
                "reason": "Invalid or malformed LLM response.",
            }
        }

    # Relevance checks
    async def check_brand_relevance(self, summary: str, search_term: str) -> dict:
        system_msg = load_search_term_prompt("brand_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"
        return self.normalize_brand(await self._call_llm(system_msg, user_msg, "brand"))

    async def check_configuration_relevance(
        self, summary: str, search_term: str
    ) -> dict:
        system_msg = load_search_term_prompt("configuration_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"
        return self.normalize_configuration(
            await self._call_llm(system_msg, user_msg, "configuration")
        )

    async def check_location_relevance(
        self, summary: str, search_term: str, brand_type: str
    ) -> dict:
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"
        return self.normalize_brand(await self._call_llm(system_msg, user_msg, "brand"))

    async def check_configuration_relevance(
        self, summary: str, search_term: str
    ) -> dict:
        system_msg = load_search_term_prompt("configuration_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"
        return self.normalize_configuration(
            await self._call_llm(system_msg, user_msg, "configuration")
        )

    async def check_location_relevance(
        self, summary: str, search_term: str, brand_type: str
    ) -> dict:
        if brand_type == "competitor":
            return {
                "location": {
                    "match": False,
                    "type": "skipped_due_to_competitor",
                    "match_level": "No Match",
                    "reason": "Search term contains a competitor brand.",
                    "reason": "Search term contains a competitor brand.",
                }
            }

        system_msg = load_search_term_prompt("location_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"

        return self.normalize_location(
            await self._call_llm(system_msg, user_msg, "location")
        )

        system_msg = load_search_term_prompt("location_relevancy_prompt.txt")
        user_msg = f"PROJECT SUMMARY:{summary}\nSEARCH TERM:{search_term}"

        return self.normalize_location(
            await self._call_llm(system_msg, user_msg, "location")
        )

    async def check_overall_relevance(
        self,
        summary: str,
        search_term: str,
        brand_result: dict,
        config_result: dict,
        location_result: dict,
        location_result: dict,
    ) -> dict:
        system_msg = load_search_term_prompt("overall_relevancy_prompt.txt")
        user_msg = (
            f"PROJECT SUMMARY:{summary}\n"
            f"SEARCH TERM:{search_term}\n"
            f"BRAND:{json.dumps(brand_result)}\n"
            f"CONFIG:{json.dumps(config_result)}\n"
            f"LOCATION:{json.dumps(location_result)}"
            f"PROJECT SUMMARY:{summary}\n"
            f"SEARCH TERM:{search_term}\n"
            f"BRAND:{json.dumps(brand_result)}\n"
            f"CONFIG:{json.dumps(config_result)}\n"
            f"LOCATION:{json.dumps(location_result)}"
        )
        return await self._call_llm(system_msg, user_msg, "overall")

    # Fetch search terms
    async def fetch_search_terms(self, customer_id: str = None) -> list:
        target_customer_id = customer_id or self.customer_id
        endpoint = f"https://googleads.googleapis.com/v20/customers/{target_customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {self.google_ads_access_token}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "Content-Type": "application/json",
        }

        duration_clause = format_date_range(self.duration)

        query = f"""
        SELECT
            ad_group.id,
            search_term_view.search_term,
            search_term_view.status,
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
            AND search_term_view.status IN ('NONE')
            AND ad_group.status = 'ENABLED'
            AND campaign.status = 'ENABLED'
        """

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint, headers=headers, json={"query": query}
                )
                data = response.json()
        except Exception as e:
            logger.error("Failed to fetch search terms", error=str(e))
            return []

        logger.info("[SearchTermService] Search terms response", response=data)
        query = f"""
        SELECT
            ad_group.id,
            search_term_view.search_term,
            search_term_view.status,
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
            AND search_term_view.status IN ('NONE')
            AND ad_group.status = 'ENABLED'
            AND campaign.status = 'ENABLED'
        """

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint, headers=headers, json={"query": query}
                )
                data = response.json()
        except Exception as e:
            logger.error("Failed to fetch search terms", error=str(e))
            return []

        logger.info("[SearchTermService] Search terms response", response=data)

        if "error" in data:
            logger.error("Google Ads API error", error=data["error"])
            return []

        results = []
        for row in data.get("results", []):
            metrics = row.get("metrics", {})
            search_view = row.get("searchTermView", {})
            segments = row.get("segments", {})
            ad_group = row.get("adGroup", {})

            term = search_view.get("searchTerm")
            if not term:
                continue

            cost_micros = int(metrics.get("costMicros", 0) or 0)

            results.append(
                {
                    "searchterm": term,
                    "status": search_view.get("status"),
                    "matchType": segments.get("searchTermMatchType"),
                    "adGroupId": ad_group.get("resourceName"),
                    "metrics": {
                        "impressions": metrics.get("impressions", 0),
                        "clicks": metrics.get("clicks", 0),
                        "ctr": metrics.get("ctr", 0),
                        "conversions": metrics.get("conversions", 0),
                        "costMicros": cost_micros,
                        "averageCpc": metrics.get("averageCpc", 0),
                        "cost": micros_to_rupees(cost_micros),
                        "costPerConversion": metrics.get("costPerConversion", 0),
                    },
                }
            )

        return results

    #  Full pipeline
    async def run_pipeline(self) -> dict:
        ads_data = await ads_service.fetch_ads(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            access_token=self.access_token,
        )

        summary = ""
        campaign_name = ""
        product_id = ""
        customer_id = ""

        if ads_data:
            first = ads_data[0]
            campaign_name = first.get("campaign_name", "")
            product_id = first.get("product_id", "")
            customer_id = first.get("customer_id", "")
            summaries = first.get("summaries", [])
            summary = summaries[0] if summaries else ""

        search_terms = await self.fetch_search_terms(customer_id=customer_id)
        if not search_terms:
            return {
                "classified_search_terms": [],
                "campaignName": campaign_name,
                "productId": product_id,
                "customerId": customer_id,
            }

        classified_terms = await analyze_search_term_performance(search_terms)

        async def process_term(term_data: dict):
            search_term = term_data.get("term") or term_data.get("searchterm")
            performances = term_data.pop("performances", {})

            brand_eval = await self.check_brand_relevance(summary, search_term)
            brand_type = brand_eval["brand"]["type"]

            config_eval, location_eval = await asyncio.gather(
                self.check_configuration_relevance(summary, search_term),
                self.check_location_relevance(summary, search_term, brand_type),
            )

            brand_match = brand_eval["brand"]["match"]
            config_match = config_eval["configuration"]["match"]

            if not brand_match and not config_match:
                overall_eval = {
                    "overall": {
                        "match": False,
                        "match_level": "No Match",
                        "intent_stage": "Irrelevant",
                        "suggestion_type": "negative",
                        "reason": "No brand, configuration, or location match.",
                    }
                }
            else:
                overall_eval = await self.check_overall_relevance(
                    summary,
                    search_term,
                    brand_eval,
                    config_eval,
                    location_eval,
                )

            term_data["evaluations"] = {
                "performances": performances,
                "relevancyCheck": {
                    "brandRelevancy": brand_eval,
                    "configurationRelevancy": config_eval,
                    "locationRelevancy": location_eval,
                },
                "overallPerformance": overall_eval,
            }

            return term_data

        classified_terms = await asyncio.gather(
            *(process_term(t) for t in classified_terms)
        )

        return {
            "classified_search_terms": classified_terms,
            "campaignName": campaign_name,
            "productId": product_id,
            "customerId": customer_id,
        }
