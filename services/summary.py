import json
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

executor = ThreadPoolExecutor()

def make_readable_sync(scraped_data):
    try:
        prompt = f"""
You are given scraped website data in JSON:
{json.dumps(scraped_data, indent=2)}

Task:
Write a clear, engaging **summary of 400–500 words in a single paragraph** that describes:
- The business purpose and mission
- Products or services offered
- Benefits or value to customers
- What makes this business unique or different

Guidelines:
- Use a professional but promotional tone (like marketing copy).
- Avoid bullet points; write in one continuous flowing paragraph.
- Ensure the content can be used later to create Google Ads assets (headlines, descriptions, keywords).
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


async def make_readable(scraped_data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, make_readable_sync, scraped_data)
