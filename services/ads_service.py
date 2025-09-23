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

def generate_ad_assets_sync(summary):
    try:
        prompt = f"""
You are a world-class advertising manager, expert copywriter, and SEO strategist.  
Your task is to analyze the following structured webpage summary JSON and generate **high-quality ad assets**.

Here is the JSON data:
{json.dumps(summary, indent=2)}

### Requirements:

1. **Headlines**
   - Generate between 8 and 12 unique headlines.
   - Each headline must be short, catchy, and persuasive.
   - Length: strictly 20-25 characters.
   - Headlines should highlight the strongest benefits, offers, or unique features.
   - Avoid quotation marks, emojis, or unnecessary punctuation.
   - Each headline must be unique (no repetitions).

2. **Descriptions**
   - Generate between 2–3 unique ad descriptions.
   - Each description must be clear, engaging, and persuasive.
   - Length: strictly between 80–85 characters.
   - Focus on value proposition, benefits, and differentiation.
   - Vary sentence structures to avoid repetition.

3. **Audience Targeting**
   - Suggest the most relevant gender(s) for the ads in an array (e.g., ["Male", "Female"]).
   - Suggest a minimum and maximum age in an array (e.g., [23, 56]).
   - Base these suggestions strictly on the provided JSON data.

### Output format:
Return the result **strictly as a valid JSON object** with the following structure:

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
        return safe_json_parse(raw_output)
    
    except Exception as e:
        return {
            "error": f"Exception occurred: {str(e)}",
            "raw_output": None
        }


async def generate_ad_assets(summary):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, generate_ad_assets_sync, summary)
