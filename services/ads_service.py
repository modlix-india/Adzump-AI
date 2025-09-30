import json
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from dotenv import load_dotenv
from services.json_utils import safe_json_parse

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
executor = ThreadPoolExecutor()

def generate_ad_assets_sync(summary, positive_keywords):
    try:
        prompt = f"""
You are a world-class advertising manager, expert copywriter, and SEO strategist.  
Your task is to analyze the following structured webpage summary JSON and generate **high-quality ad assets**.

Here is the summary JSON:
{json.dumps(summary, indent=2)}

Here are the **positive keywords** you MUST use in the ad assets:
{json.dumps(positive_keywords, indent=2)}

### Requirements:

1. **Headlines**
   - Generate between 30 to 40 unique headlines.
   - Each headline must be 25-30 characters include spacing.
   - Each headline must be short, catchy, and persuasive.
   - Each headline MUST include at least one keyword from the provided positive keywords.
   - Highlight benefits, offers, or unique features.
   - Avoid quotation marks, emojis, or unnecessary punctuation.
   - Each headline must be unique.

2. **Descriptions**
   - Generate between 10–15 unique ad descriptions.
   - Each description must be 85-90 characters include spacing.
   - Each description MUST include at least one keyword from the provided positive keywords.
   - Focus on value proposition, benefits, and differentiation.
   - Vary sentence structures to avoid repetition.

3. **Audience Targeting**
   - Suggest the most relevant gender(s) in an array (e.g., ["Male", "Female"]).
   - Suggest a min and max age in an array (e.g., [23, 56]).
   - Base on the provided JSON data.

### Output format:
Return strictly as a valid JSON object:

{{
  "headlines": ["Headline 1", "Headline 2", ...],
  "descriptions": ["Description 1", "Description 2", ...],
  "audience": {{
      "gender": ["Male", "Female"],
      "age_range": [23, 56]
  }}
}}
Do not include explanations, comments, or extra text outside the JSON object.
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        raw_output = response.choices[0].message.content.strip()
        parsed = safe_json_parse(raw_output)

        if not parsed:
            return parsed

        if "headlines" in parsed:
            filtered_headlines = [
                h for h in parsed["headlines"]
                if len(h) <= 30
            ]
            filtered_headlines = sorted(filtered_headlines, key=len)
            parsed["headlines"] = filtered_headlines[:15]

        if "descriptions" in parsed:
            filtered_descriptions = [
                d for d in parsed["descriptions"]
                if len(d) <= 85
            ]
            filtered_descriptions = sorted(filtered_descriptions, key=len)
            parsed["descriptions"] = filtered_descriptions[:4]

        return parsed

    except Exception as e:
        return {
            "error": f"Exception occurred: {str(e)}",
            "raw_output": None
        }


async def generate_ad_assets(summary, positive_keywords):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, generate_ad_assets_sync, summary, positive_keywords)