import json
import structlog
from fastapi import HTTPException
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from services.business_service import BusinessService

PROMPT = load_prompt("meta/meta_campaign_prompt.txt")
logger = structlog.get_logger()


class MetaCampaignService:

    @staticmethod
    async def generate_campaign(
        data_object_id: str,
        access_token: str,
        client_code: str,
        business_name: str,
        goal: str,
        x_forwarded_host: str = None,
        x_forwarded_port: str = None,
    ) -> dict:

        # Fetch product/business data
        product_data = await BusinessService.fetch_product_details(
            data_object_id,
            access_token,
            client_code,
            x_forwarded_host,
            x_forwarded_port
        )

        summary = product_data.get("summary", "")
        if not summary:
            logger.error("Missing 'summary' in product data", data_object_id=data_object_id)
            raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

        # Build prompt
        prompt = PROMPT.format(
            summary=summary
        )

        messages = [
            {"role": "system", "content": "Respond only with valid JSON"},
            {"role": "user", "content": prompt}
        ]

        response = await chat_completion(messages)
        content = response.choices[0].message.content

        # Log the raw LLM output
        logger.info("LLM raw output", content=content, data_object_id=data_object_id)

        if not content:
            logger.error("LLM returned empty response", data_object_id=data_object_id)
            raise HTTPException(status_code=500, detail="LLM returned empty response")

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse LLM output as JSON",
                error=str(e),
                raw_output=content,
                data_object_id=data_object_id
            )
            raise HTTPException(status_code=500, detail="LLM output is not valid JSON")
