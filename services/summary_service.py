from fastapi import HTTPException
import logging
from services.openai_client import chat_completion
from utils.prompt_loader import format_prompt

logger = logging.getLogger(__name__)

async def generate_summary(scraped_data: dict):
    if not scraped_data:
        raise HTTPException(status_code=400, detail="scraped_data cannot be empty")

    try:
        prompt = format_prompt("website_summary_prompt.txt", scraped_data=scraped_data)
        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini"
        )
        content = response.choices[0].message.content.strip()
        return {"summary": content}

    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")
