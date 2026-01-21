import json
import structlog
from fastapi import HTTPException
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from services.business_service import BusinessService
from services.meta.meta_adset_targeting_mapper import build_meta_targeting

logger = structlog.get_logger()
PROMPT = load_prompt("meta/meta_adset_prompt.txt")


class MetaAdSetService:

    @staticmethod
    async def generate_adset(
        data_object_id: str,
        access_token: str,
        client_code: str,
        goal: str,
        region: str,
        ad_account_id: str,
        x_forwarded_host: str = None,
        x_forwarded_port: str = None,
    ) -> dict:

        product_data = await BusinessService.fetch_product_details(
            data_object_id=data_object_id,
            access_token=access_token,
            client_code=client_code,
            x_forwarded_host=x_forwarded_host,
            x_forwarded_port=x_forwarded_port
        )

        summary = product_data.get("summary") or product_data.get("finalSummary")
        if not summary:
            logger.error(
                "Missing summary in product data",
                data_object_id=data_object_id,
                available_keys=list(product_data.keys())
            )
            raise HTTPException(
                status_code=400,
                detail="Missing summary in product data. Please ensure website analysis is complete."
            )

        prompt = PROMPT.format(
            summary=summary,
            goal=goal,
            region=region
        )

        response = await chat_completion([
            {"role": "system", "content": "Return only valid JSON"},
            {"role": "user", "content": prompt},
        ])

        content = response.choices[0].message.content
        logger.info("Meta AdSet LLM output", content=content)

        try:
            llm_output = json.loads(content)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=500,
                detail="Invalid JSON returned by LLM"
            )

        targeting = await build_meta_targeting(
            llm_output=llm_output,
            ad_account_id=ad_account_id,
            access_token=access_token,
            region=region
        )

        llm_output["targeting"] = targeting
        return llm_output
