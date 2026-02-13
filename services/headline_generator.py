import structlog

from services.openai_client import chat_completion
from services.json_utils import safe_json_parse
from utils import prompt_loader
from core.optimization.similarity_matcher import SimilarityMatcher

logger = structlog.get_logger(__name__)


class HeadlineGenerator:
    async def generate_suggestions(
        self,
        low_asset: dict,
        similar_assets: list,
        source_tier: str,
        campaign_name: str,
        ad_group_name: str,
    ) -> list:
        # Build examples text based on source tier
        if similar_assets:
            examples_text = "\n".join(
                [
                    f'- "{item["asset"]["text"]}" '
                    f"({item['asset']['label']}, {item['asset']['impressions']} impressions, "
                    f"similarity: {item['similarity']:.2f})"
                    for item in similar_assets
                ]
            )
            context_note = f"Learn from these {source_tier} examples:"

        elif source_tier == "campaign_context":
            # Extract keywords for context
            keywords = SimilarityMatcher.extract_keywords(campaign_name, ad_group_name)

            examples_text = (
                "NO EXAMPLE ASSETS AVAILABLE.\n"
                f"Generate based on campaign context:\n"
                f"- Campaign: {campaign_name}\n"
                f"- Ad Group: {ad_group_name}\n"
                f"- Keywords to use: {', '.join(keywords)}\n\n"
                f"Create compelling headlines incorporating these keywords naturally."
            )
            context_note = "Campaign context:"

        else:
            examples_text = (
                "NO CAMPAIGN CONTEXT AVAILABLE.\n"
                "Generate general best-practice headlines that:\n"
                "- Are action-oriented and compelling\n"
                "- Have broad appeal\n"
                "- Follow Google Ads best practices\n"
                "- Are clear and concise"
            )
            context_note = "General best practices:"

        prompt = prompt_loader.format_prompt(
            "optimization/headline_optimization_prompt.txt",
            count=5,  # Generate 5 options, pick best 1 after validation
            campaign_name=campaign_name,
            ad_group_name=ad_group_name,
            current_text=low_asset.get("text", ""),
            examples=examples_text,
            context_note=context_note,
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.8,
        )

        raw_output = response.choices[0].message.content.strip()
        suggestions = safe_json_parse(raw_output)

        return suggestions if isinstance(suggestions, list) else []
