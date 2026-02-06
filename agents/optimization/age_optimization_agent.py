import json
from structlog import get_logger

from core.services.campaign_mapping import campaign_mapping_service
from core.models.optimization import OptimizationResponse, CampaignRecommendation
from adapters.google.accounts import GoogleAccountsAdapter
from adapters.google.optimization.age import GoogleAgeAdapter
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


# TODO: Filter recommendations based on existing targeting:
#   - ADD recommendations: only for age ranges not already targeted
#   - REMOVE recommendations: only for age ranges already targeted
class AgeOptimizationAgent:
    def __init__(self):
        self.accounts_adapter = GoogleAccountsAdapter()
        self.age_adapter = GoogleAgeAdapter()

    async def generate_recommendations(self, client_code: str) -> dict:
        accounts = await self.accounts_adapter.fetch_accessible_accounts(client_code)
        if not accounts:
            logger.info("No accessible accounts found", client_code=client_code)
            return {"recommendations": []}

        campaign_product_map = await campaign_mapping_service.get_campaign_product_mapping(client_code)

        all_recommendations: list[CampaignRecommendation] = []
        for account in accounts:
            recommendations = await self._process_google_account(
                account=account,
                campaign_product_map=campaign_product_map,
            )
            all_recommendations.extend(recommendations)

        return {"recommendations": [r.model_dump() for r in all_recommendations]}

    async def _process_google_account(
        self,
        account: dict,
        campaign_product_map: dict,
    ) -> list[CampaignRecommendation]:
        """Process a single Google Ads account."""
        account_id = account["customer_id"]
        parent_account_id = account["login_customer_id"]

        metrics = await self.age_adapter.fetch_age_metrics(account_id, parent_account_id)
        if not metrics:
            return []

        linked_metrics = self._filter_linked_google_campaigns(metrics, campaign_product_map)
        if not linked_metrics:
            logger.info(
                "No linked campaigns for account",
                account_id=account_id,
                total_campaigns=len(metrics),
            )
            return []

        return await self._analyze_google_metrics(linked_metrics, account_id, parent_account_id)

    def _filter_linked_google_campaigns(
        self, metrics: list, campaign_product_map: dict
    ) -> list:
        """Filter metrics to only campaigns with linked products."""
        linked = []
        for m in metrics:
            campaign_id = str(m.get("campaign", {}).get("id"))
            if campaign_id in campaign_product_map:
                m["product_id"] = campaign_product_map[campaign_id]
                linked.append(m)
        return linked

    async def _analyze_google_metrics(
        self, metrics: list, account_id: str, parent_account_id: str
    ) -> list[CampaignRecommendation]:
        """Send metrics to LLM for analysis and return parsed recommendations."""
        prompt = load_prompt("optimization/age_optimization_prompt.txt")
        formatted = prompt.format(
            platform="google_ads",
            parent_account_id=parent_account_id,
            account_id=account_id,
            metrics=json.dumps(metrics, indent=2),
        )

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Google Ads analyst."},
                {"role": "user", "content": formatted},
            ],
            model="gpt-4o-mini",
        )

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response) -> list[CampaignRecommendation]:
        """Parse and validate LLM response."""
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()

        parsed = OptimizationResponse.model_validate_json(content)
        return list(parsed.recommendations)


age_optimization_agent = AgeOptimizationAgent()
