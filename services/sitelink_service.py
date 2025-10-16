from fastapi import HTTPException
from typing import List, Dict, Any
from urllib.parse import urlparse
import json
import re

from services.openai_client import chat_completion  # ✅ Using your OpenAI client
from utils.text_utils import is_internal_link
from utils.prompt_loader import load_prompt
from oserver.connection import fetch_product_details


# ---------------- Core: Generate sitelinks (after fetching data) ---------------- #
async def generate_sitelinks_service(data_object_id: str, access_token: str, client_code: str):
    """
    Fetch data from CoreServices and generate sitelinks using LLM.
    """
    product_data = fetch_product_details(data_object_id, access_token, client_code)
    

    if not product_data or not isinstance(product_data, list):
        raise HTTPException(status_code=500, detail="Invalid product data response")

    product_result = product_data[0].get("result", {}).get("result", {})
    summary = product_result.get("summary", "")
    base_url = product_result.get("businessUrl", "")
    links = product_result.get("siteLinks", [])
 
    if not base_url or not summary:
        raise HTTPException(status_code=400, detail="Missing 'summary' or 'businessUrl' in product data")

    return await generate_sitelinks(links, base_url, summary)

# ---------------- Core: Generate Sitelinks ---------------- #
async def generate_sitelinks(links: List[Dict[str, Any]], base_url: str, summary: str):
    """
    Generate high-quality Google Ads sitelinks from given links and site summary.
    Focuses on internal, lead-generating pages with strong ad potential.
    """
    base_domain = urlparse(base_url).netloc.replace("www.", "").lower()

    # Step 1: Filter valid internal links
    valid_links = [
        l for l in links
        if l.get("text", "").strip()
        and l.get("href", "").strip()
        and is_internal_link(l["href"], base_domain)
    ]

    if not valid_links:
        return []
    # print(valid_links)
    
    # Step 2: Load prompt from file
    
    prompt_template = load_prompt("sitelinks_prompt.txt")

    # Step 3: Format with dynamic values
    prompt = prompt_template.format(
    summary=summary,
    base_url=base_url,
    links_json=json.dumps(valid_links, indent=2)  # Pass JSON string here
)
    


    # Step 3: Call GPT model
    response = await chat_completion(
        messages=[
            {"role": "system", "content": "You are a precise JSON generator. Return only valid JSON arrays."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o-mini"
    )

    content = response.choices[0].message.content.strip()
    # print("🔹 LLM raw response:", content)

    # Step 4: Safely parse JSON
    try:
        sitelinks = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            sitelinks = json.loads(match.group(0))
        else:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {content}")

    # Step 5: Enforce character limits (safety)
    formatted_sitelinks = []
    for s in sitelinks:
        formatted_sitelinks.append({
            "sitelink_text": s.get("sitelink_text", "")[:25],
            "description_1": s.get("description_1", "")[:35],
            "description_2": s.get("description_2", "")[:35],
            "final_url": s.get("final_url", "")
        })

    return formatted_sitelinks
