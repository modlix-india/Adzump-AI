from fastapi import HTTPException
import json
import re
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt


class BaseAssetService:
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
