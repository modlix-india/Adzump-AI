import json
from services.json_utils import safe_json_parse
from services.openai_client import chat_completion
from utils import prompt_loader
from structlog import get_logger

logger = get_logger(__name__)

async def generate_ad_assets(summary, positive_keywords):
    try:
        prompt = prompt_loader.format_prompt(
            "ad_assets_prompt.txt", 
            summary_json=json.dumps(summary, indent=2),
            positive_keywords_json=json.dumps(positive_keywords, indent=2)
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.7
        )
        if response.usage:
            logger.info(
                "[AdAssets] Token usage",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )

        raw_output = response.choices[0].message.content.strip()
        parsed = safe_json_parse(raw_output)

        if not parsed:
            return parsed

        if "headlines" in parsed:
            filtered_headlines = [
                h for h in parsed["headlines"]
                if len(h) >= 20 and len(h) <= 30
            ]
            filtered_headlines = sorted(filtered_headlines, key=len)
            parsed["headlines"] = filtered_headlines[:15]

        if "descriptions" in parsed:
            filtered_descriptions = [
                d for d in parsed["descriptions"]
                if len(d) >= 80 and len(d) <= 90
            ]
            filtered_descriptions = sorted(filtered_descriptions, key=len)
            parsed["descriptions"] = filtered_descriptions[:4]

        return parsed

    except Exception as e:
        return {
            "error": f"Exception occurred: {str(e)}",
            "raw_output": None
        }