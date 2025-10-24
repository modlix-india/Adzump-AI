from fastapi import HTTPException
import json
import re

from services.openai_client import chat_completion 
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_product_details


# ---------------- Core: Generate Structured Snippets (after fetching data) ---------------- #
async def generate_structured_snippets_service(data_object_id: str, access_token: str, client_code: str):
    """
    Fetch data from CoreServices and generate structured snippets using LLM.
    """
    product_data = fetch_product_details(data_object_id, access_token, client_code)

    if not product_data or not isinstance(product_data, list):
        raise HTTPException(status_code=500, detail="Invalid product data response")

    product_result = product_data[0].get("result", {}).get("result", {})
    summary = product_result.get("summary", "")

    if not summary:
        raise HTTPException(status_code=400, detail="Missing 'summary' in product data")

    return await generate_structured_snippets(summary)


# ---------------- Core: Generate Structured Snippets ---------------- #
async def generate_structured_snippets(summary: str):
    """
    Generate structured snippet assets (header + values) from business summary.
    """
    prompt_template = load_prompt("structured_snippet_prompt.txt")
    prompt = prompt_template.replace("{summary}", summary)

    response = await chat_completion(
        messages=[
            {"role": "system", "content": "Return only valid JSON arrays with header and values."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o-mini"
    )

    content = response.choices[0].message.content.strip()

    try:
        snippets = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            snippets = json.loads(match.group(0))
        else:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {content}")

    formatted_snippets = []
    for s in snippets:
        header = s.get("header", "")[:25]
        values = [v[:25] for v in s.get("values", []) if v.strip()]
        if header and values:
            formatted_snippets.append({"header": header, "values": values})

    return formatted_snippets
