from fastapi import HTTPException
import json
import re
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.services.storage_service import read_storage
from oserver.models.storage_request_model import StorageRequest


class BaseAssetService:

    @staticmethod
    async def fetch_product_details(data_object_id: str, access_token: str, client_code: str):
        payload = StorageRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            dataObjectId=data_object_id,
            eager=False,
            eagerFields=[]
        )

        response = await read_storage(payload, access_token, client_code)

        if not response.success or not response.result:
            raise HTTPException(status_code=500, detail=response.error or "Failed to fetch product details")

        data = response.result

        try:
            if isinstance(data, list) and len(data) > 0:
                product_data = data[0]["result"]["result"]
            elif isinstance(data, dict) and "result" in data:
                product_data = data["result"]["result"]
            else:
                raise HTTPException(status_code=500, detail="Unexpected product data format")
        except (KeyError, IndexError, TypeError):
            raise HTTPException(status_code=500, detail="Invalid product data response structure")

        return product_data

    @staticmethod
    async def generate_from_prompt(prompt_name: str, prompt_vars: dict, model: str = "gpt-4o-mini"):
        prompt_template = load_prompt(prompt_name)
        prompt = prompt_template.format(**prompt_vars)

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are a precise JSON generator. Return only valid JSON arrays."},
                {"role": "user", "content": prompt},
            ],
            model=model
        )

        content = response.choices[0].message.content.strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\[[\s\S]*\]", content)
            if match:
                data = json.loads(match.group(0))
            else:
                raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {content}")

        return data
