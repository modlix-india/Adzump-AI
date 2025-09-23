import json
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

executor = ThreadPoolExecutor()

def summarize_with_context_sync(scraped_data, context):
    try:
        prompt = f"""
You are given scraped website data in JSON:
{json.dumps(scraped_data, indent=2)}

User Instruction (Context):
{context}

Task:
Write a clear, engaging **summary of 400–500 words in a single paragraph** that:
- Uses the scraped data as the factual base.
- Follows the user’s instruction/context (e.g., focus on sustainability, highlight luxury, target investors).
- Describes the business purpose, products/services, benefits to customers, and unique selling points.
- Uses a professional but promotional tone (like marketing copy).
- Avoid bullet points; write in one continuous flowing paragraph.
- Ensure the content can later be used to create Google Ads assets (headlines, descriptions, keywords).
- Do NOT include any meta commentary.
- Return ONLY the paragraph text (no JSON, no arrays, no code blocks).
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )

        raw_output = response.choices[0].message.content.strip()

        return {"summary": raw_output}

    except Exception as e:
        return {
            "error": f"Exception occurred: {str(e)}",
            "raw_output": None
        }


async def summarize_with_context(scraped_data, context):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, summarize_with_context_sync, scraped_data, context)
