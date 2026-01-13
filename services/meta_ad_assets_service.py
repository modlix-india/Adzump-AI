import json
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt

PROMPT_TEMPLATE = load_prompt("meta_ad_assets_prompt.txt")


class MetaAdAssetsService:

    @staticmethod
    async def generate_ad_assets(
        business_name: str,
        website_url: str,
        goal: str
    ) -> dict:

        prompt = PROMPT_TEMPLATE.format(
            business_name=business_name,
            website_url=website_url,
            goal=goal
        )

        messages = [
            {
                "role": "system",
                "content": "You are a marketing expert. Respond only with valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        return json.loads(content)
