from fastapi import HTTPException
from typing import List, Dict, Any
from urllib.parse import urlparse
import json
import re
import requests
import os

from services.openai_client import chat_completion  # ✅ Using your OpenAI client
from utils.text_utils import is_internal_link
from utils.prompt_loader import load_prompt


def fetch_product_details(data_object_id: str,access_token:str, clientCode:str):

    base = (os.getenv("NOCODE_PLATFORM_HOST") or "").rstrip("/")
    if not base:
        raise RuntimeError("NOCODE_PLATFORM_HOST is not set")
    
    url = f"{base}/api/core/function/execute/CoreServices.Storage/Read"

    headers = {
        "authorization": access_token,
        "content-type": "application/json",
        "clientCode": clientCode
    }

    payload = {
        "storageName": "AISuggestedData",
        "appCode": "marketingai",
        "dataObjectId": data_object_id,
        "eager": False,
        "eagerFields": []
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error fetching product details: {e}")
        return None


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

    content = response.strip()
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
