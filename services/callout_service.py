from fastapi import HTTPException
import json
import re

from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_product_details


# ---------------- Core: Generate Callouts (after fetching data) ---------------- #
async def generate_callouts_service(data_object_id: str, access_token: str, client_code: str):
    """
    Fetch data from CoreServices and generate callouts using LLM.
    """
    product_data = fetch_product_details(data_object_id, access_token, client_code)

    if not product_data or not isinstance(product_data, list):
        raise HTTPException(status_code=500, detail="Invalid product data response")

    product_result = product_data[0].get("result", {}).get("result", {})
    summary = product_result.get("summary", "")

    if not summary:
        raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

    return await generate_callouts(summary)


# ---------------- Core: Generate Callouts ---------------- #
async def generate_callouts(summary: str):
    """
    Generate short, persuasive callout assets from summary text.
    """
    prompt_template = load_prompt("callouts_prompt.txt")
    prompt = prompt_template.format(summary=summary)

    response = await chat_completion(
        messages=[
            {"role": "system", "content": "You are a precise JSON generator. Return only valid JSON arrays."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o-mini"
    )

    content = response.choices[0].message.content.strip()

    try:
        callouts = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            callouts = json.loads(match.group(0))
        else:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {content}")

    # Enforce Google Ads limits (max 25 chars)
    formatted_callouts = [{"callout_text": c[:25]} for c in callouts if isinstance(c, str) and c.strip()]

    return formatted_callouts
