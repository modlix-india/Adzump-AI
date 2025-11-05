import os
import json
import logging
import requests
import utils.date_utils as date_utils
from third_party.google.services import keywords_service, ads_service
from services.search_term_analyzer import analyze_search_term_performance
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

 
    # LLM Configuration Relevance

    async def check_configuration_relevance(self, summary: str, search_term: str):
        """
        Stronger LLM prompt: first extract configuration facts + evidence from summary,
        then evaluate the search term against those facts. Returns a dict with:
        - configuration: { match, score, match_level, reason }
        """
        
        system_msg = (
            "You are a real-estate configuration relevance evaluator.\n"
            "Your task is to determine whether a SEARCH TERM explicitly refers to any configuration type "
            "that is also described in the PROJECT SUMMARY.\n\n"

            "CONFIGURATION RELEVANCY RULES\n"
    
                " - Only consider configuration relevance if the SEARCH TERM itself explicitly contains configuration-related words, "
                " - such as '1BHK', '2BHK', '3BHK', '4BHK', 'villa', 'apartment', 'flat', 'plot', or 'duplex'.\n\n"
                " - If the SEARCH TERM does NOT contain any configuration words, configurationRelevancy.match must be false.\n"
                " - Even if the project summary includes configuration information, ignore it.\n\n"

                " - If configuration words are found in the SEARCH TERM, check if those configurations are mentioned in the PROJECT SUMMARY.\n"
                " - If found, configurationRelevancy.match = true and provide evidence from the summary.\n"
                " - If not found, configurationRelevancy.match = false and explain that the project does not offer that configuration.\n\n"

                "Do NOT infer or assume configuration intent based on related terms like 'price', 'project', or 'location'. "
                "Those are not configuration indicators.\n\n"

            "OUTPUT REQUIREMENTS\n"
                " - Always include 'found_configurations' (list of configuration facts and evidence only if the term contains configuration words).\n"
                " - The 'reason' must clearly state whether configuration relevance was triggered by the term or ignored due to lack of configuration mentions.\n"
        )


        user_msg = f"""
            PROJECT SUMMARY:
            {summary}

            SEARCH TERM:
            {search_term}

            Return ONLY valid JSON with this exact shape:
            {{
            "configuration": {{
                "match": true or false,
                "score": 0.0 to 1.0,
                "match_level": "Perfect Match|Strong Match|Medium Match|Weak Match|No Match",
                "reason": "One-sentence explanation that cites the facts above (or explains why none were usable)."
            }}
            }}
        """

        try:
            response = await chat_completion(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()

            # Basic sanitization: remove fences and common lead-ins

            cleaned = (
                content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

            # If model added extra text, extract first {...} block

            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)

            result = json.loads(cleaned)

            # Validate structure
            if "configuration" not in result:
                raise ValueError("LLM returned JSON missing required keys")

            # quick sanity: ensure configuration has required keys
            cfg = result["configuration"]
            if not all(k in cfg for k in ("match", "score", "match_level", "reason")):
                raise ValueError("configuration object missing keys")

            
            return result

        except json.JSONDecodeError:
            logger.warning("Invalid JSON from LLM; falling back to conservative No Match result.")
            return {
                "configuration": {
                    "match": False,
                    "score": 0.0,
                    "match_level": "No Match",
                    "reason": "Unable to parse LLM output; defaulting to No Match. (Try re-running or check logs.)"
                }
            }
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return {
                "configuration": {
                    "match": False,
                    "score": 0.0,
                    "match_level": "No Match",
                    "reason": "Temporary error during relevance evaluation. Defaulting to No Match."
                }
            }
   
    # LLM Brand Relevance
    async def check_brand_relevance(self, summary: str, search_term: str):
        """
        Strict version: Detects own brand vs competitor vs generic.
        Ensures only brands present in the PROJECT SUMMARY are treated as own brands.
        """
        system_msg = (
            "You are a precise real-estate brand and project identification expert.\n"
            "Your goal is to determine if a SEARCH TERM refers to the same project as described in the PROJECT SUMMARY, "
            "a competitor brand, or is generic.\n\n"

            "BRAND MATCHING RULES\n"
                "1.First, read the PROJECT SUMMARY carefully. Extract all clear brand or developer identifiers "
                "(e.g., 'Earthen Ambience', 'Evantha', 'Valmark CityVille', 'Keya Life by the Lake'). "
                "These represent the project's official brand.\n\n"

                "2.If ANY of those identifiers appear in the SEARCH TERM (case-insensitive substring), "
                "it is considered the project’s **own brand**.\n"
                "   → match = true\n"
                "   → type = 'own_brand'\n"
                "   → competitor_detected = false\n\n"

                "3.If the SEARCH TERM includes other proper nouns or brand-like words that are NOT found in the PROJECT SUMMARY, "
                "check if they co-exist with the project’s brand:\n"
                "   - If the term mainly centers around the project’s own brand (even with extra local or builder info), "
                "     treat it as **own brand**.\n"
                "   - Only if the main phrase refers to a completely different project or developer, mark as **competitor**.\n\n"

                "4.Ignore configuration and location terms (e.g., 'villa', 'apartments', 'Bangalore', 'Whitefield', 'Sarjapur'). "
                "They do not affect brand detection.\n\n"

                "5.If there is no identifiable brand or developer name, classify as **generic**.\n\n"

            "OUTPUT REQUIREMENTS\n"
                "- Always include 'found_brands' (list of all brand or developer names detected in the term).\n"
                "- Prefer summary evidence: if a brand name from the summary is found, that overrides other hints.\n"
                "- Only mark competitor_detected = true if the detected brand name is completely unrelated to the summary.\n"
                "- Provide a clear 'reason' showing what brand evidence was found and how the decision was made.\n"
        )
        
        user_msg = f"""
        PROJECT SUMMARY:
        {summary}

        SEARCH TERM:
        {search_term}

        Return only valid JSON exactly like this:
        {{
        "brand": {{
            "match": true or false,
            "type": "own_brand" or "competitor" or "generic",
            "competitor_detected": true or false,
            "score": 0.0 to 1.0,
            "match_level": "Perfect Match" | "Strong Match" | "Weak Match" | "No Match",
            "reason": "Brief explanation of why this classification was made, referencing the summary or search term."
        }}
        }}
        """

        try:
            response = await chat_completion(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=400,
            )

            content = response.choices[0].message.content.strip()
            cleaned = content.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)

            result = json.loads(cleaned)

            if "brand" not in result:
                raise ValueError("Missing required keys in brand relevance result")

            return result

        except json.JSONDecodeError:
            logger.warning("Invalid JSON from LLM; fallback to generic No Match (brand).")
            return {
                
                "brand": {
                    "match": False,
                    "type": "generic",
                    "competitor_detected": False,
                    "score": 0.0,
                    "match_level": "No Match",
                    "reason": "Unable to parse brand relevance; defaulting to generic non-match.",
                },
            }

        except Exception as e:
            logger.error(f"Brand relevance LLM failed: {e}")
            return {
                "brand": {
                    "match": False,
                    "type": "generic",
                    "competitor_detected": False,
                    "score": 0.0,
                    "match_level": "No Match",
                    "reason": "Temporary error during brand relevance evaluation.",
                },
            }

    # Overall Relevancy Check
    async def evaluate_overall_relevance(self, summary, search_term, brand_result, config_result):
        """
        Final decision layer.
        Uses LLM reasoning (no math) to combine brand and configuration relevance
        into one final classification and suggestion.
        """
        system_msg = (
            "You are an AI evaluator that finalizes search-term intent and keyword recommendations for real estate campaigns.\n"
            "You will receive the PROJECT SUMMARY, SEARCH TERM, and prior evaluation outputs (brand relevancy, configuration relevancy, and performance metrics).\n\n"

            "GOAL: Decide whether the search term should be added as a positive keyword, negative keyword, or ignored.\n\n"

            " DECISION RULES:\n"
            "1. OWN BRAND → If the term or its subparts contain the project's brand or developer name "
            "(case-insensitive, even merged like 'evanthasridurga' or 'valmarkcityville'), mark as POSITIVE.\n"
            "   - These indicate the user is directly searching for your project or builder.\n"
            "   - Always recommend: 'Add as Positive Keyword'.\n\n"

            "2. COMPETITOR → If the term contains another builder or project brand not found in the summary, mark as NEGATIVE.\n"
            "   - Recommend: 'Add as Negative Keyword'.\n\n"

            "3. GENERIC → If it has only location/configuration words, mark as NEUTRAL.\n"
            "   - Recommend: 'Exclude / Negative Keyword'.\n\n"

            "4. PERFORMANCE ADJUSTMENT:\n"
            "   - If performance metrics are positive (CTR > 0.05, CPC affordable), strengthen positive classification.\n"
            "   - If performance is poor and generic, lean toward negative.\n\n"

            " Respond strictly in JSON:\n"
            "{\n"
            "  \"overall\": {\n"
            "    \"match\": true/false,\n"
            "    \"match_level\": \"Strong Match\" | \"Moderate Match\" | \"Weak Match\" | \"No Match\",\n"
            "    \"intent_stage\": \"Positive Intent\" | \"Competitor Intent\" | \"Irrelevant\" | \"Needs Optimization\",\n"
            "    \"suggestion_type\": \"positive\" | \"negative\" | \"neutral\",\n"
            "    \"reason\": \"Short justification with reference to brand or summary match.\"\n"
            "  }\n"
            "}\n"
        )

        user_msg = f"""
        PROJECT SUMMARY:
        {summary}

        SEARCH TERM:
        {search_term}

        BRAND RELEVANCE RESULT:
        {json.dumps(brand_result, indent=2)}

        CONFIGURATION RELEVANCE RESULT:
        {json.dumps(config_result, indent=2)}

        Your job: Produce a single final judgment by reasoning logically — not with numbers — and follow the rules above.
        """

        try:
            response = await chat_completion(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            cleaned = content.replace("```json", "").replace("```", "").strip()

            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)

            result = json.loads(cleaned)

            return result

        except Exception as e:
            logger.error(f"Final overall LLM failed: {e}")
            return {
                "overall": {
                    "match": False,
                    "match_level": "No Match",
                    "suggestion_type": "neutral",
                    "reason": "Temporary LLM error during overall evaluation."
                }
            }


    # Fetch Search Terms
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
                ad_group_id = ad_group.get("resourceName")
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
                    "adGroupId": ad_group_id,
                    "metrics": {
                        "impressions": metrics.get("impressions", 0) or 0,
                        "clicks": metrics.get("clicks", 0) or 0,
                        "ctr": float(metrics.get("ctr", 0) or 0),
                        "conversions": float(metrics.get("conversions", 0) or 0),
                        "costMicros": int(metrics.get("costMicros", 0) or 0),
                        "averageCpc": float(metrics.get("averageCpc", 0) or 0),
                        "cost": (int(metrics.get("costMicros", 0) or 0)) / 1_000_000,
                        "costPerConversion": float(metrics.get("costPerConversion", 0) or 0),
                    },
                })

            return search_terms

        except Exception as e:
            logger.exception(f"Error fetching search terms: {e}")
            return []


    async def run_pipeline(self) -> list:
        """Full flow: ads summary → keywords → search terms → metrics + LLM relevance."""
        logger.info("Running full search term analysis pipeline...")

        # Fetch ads/project summary (main context for LLM)

        ads_data = await ads_service.fetch_ads(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            access_token=self.access_token,
        )

        summary = ads_data.get("summary") if isinstance(ads_data, dict) else ""
        
        #Fetch campaign keywords

        keywords = await keywords_service.fetch_keywords(
            client_code=self.client_code,
            customer_id=self.customer_id,
            login_customer_id=self.login_customer_id,
            campaign_id=self.campaign_id,
            duration=self.duration,
        )
        if not keywords:
            logger.warning("No keywords found — skipping search term fetch.")
            return []

        # Fetch search terms from keywords
        search_terms = self.fetch_search_terms(keywords)
        if not search_terms:
            logger.warning("No search terms found — skipping classification.")
            return []

        # Analyze term metrics (CTR, CPC, performance-based labels)
        classified_terms = await analyze_search_term_performance(search_terms)

        for term_data in classified_terms:
            search_term = term_data["term"]

            performances = term_data.pop("performances", {})
            if "classification" in term_data or "recommendation" in term_data:
                performances["cpc"] = {
                    "classification": term_data.pop("classification", None),
                    "recommendation": term_data.pop("recommendation", None)
                }

            #Brand and Configuration Relevance (independent LLM calls)
            config_eval = await self.check_configuration_relevance(summary, search_term)
            brand_eval = await self.check_brand_relevance(summary, search_term)

            brand_match = brand_eval["brand"]["match"]
            config_match = config_eval["configuration"]["match"]

            if not brand_match and not config_match:
                # Both irrelevant — skip further LLM calls
                summary_eval = {
                    "intent_stage": "Irrelevant",
                    "overall_classification": "Negative",
                    "insight": "No brand or configuration match found — unrelated to project.",
                    "recommendation": "Exclude / Add as Negative Keyword"
                }
            else:
                # Either relevant → do overall evaluation (LLM reasoning)
                summary_eval = await self.evaluate_overall_relevance(
                    summary,
                    search_term,
                    brand_eval,
                    config_eval
                )

            # Merge all evaluation results neatly
            term_data["evaluations"] = {
                "performances": performances,
                "relevancyCheck": {
                    "configurationRelevancy": config_eval,
                    "brandRelevancy": brand_eval
                },
                "overallPerformance": summary_eval
            }

        logger.info("Search term pipeline completed successfully.")
        return {"classified_search_terms": classified_terms}

