from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from openai import AsyncOpenAI
import os
import json
import re


client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ----- Core Logic -----
async def generate_sitelinks(links: List[Dict[str, Any]], base_url: str):
    # Filter invalid links first
    valid_links = [l for l in links if l["text"].strip() and not l["href"].startswith(("javascript:void(0)", "tel:"))]
    if not valid_links:
        return []

    # Limit to top 10 links
    valid_links = valid_links[:10]

    # Build a table of link text and href for GPT
    table_lines = "\n".join([f"- text: {l['text']} | href: {l['href']}" for l in valid_links])

    prompt = f"""
You are a senior Google Ads copywriter.
I will provide a list of link texts and hrefs from a website. Your goal is to create **high-converting sitelink descriptions** for Google Ads.

### LINKS:
{table_lines}

### TASK:
- For each link, generate:
  - "description_1": max 35 characters, persuasive and engaging
  - "description_2": max 35 characters, supporting benefit
-Select **up to 10** of the most relevant links likely to generate **high-quality leads**
- Only select links that are **highly relevant and likely to generate leads**
- **Do NOT include random or low-value links**
- Do NOT change the link text; it will be used as sitelink_text
- Do NOT generate final_url; we will assign it
- Generate **only valid JSON**, array of objects in the format:

[
  {{
    "link_text": "Master Plan",
    "description_one": "string max 35 chars",
    "description_two": "string max 35 chars"
  }}
]

- Keep responses short and strictly JSON, no extra text or markdown.
"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You only respond with valid JSON arrays. No explanations, no markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
    )

    content = response.choices[0].message.content.strip()
    # print("🔹 LLM raw response:", content)

    # --- Parse JSON safely ---
    try:
        descriptions = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            descriptions = json.loads(match.group(0))
        else:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {content}")

    # --- Combine descriptions with original links to build final sitelinks ---
    sitelinks = []
    for item in descriptions:
        # Find matching original link
        original = next((l for l in valid_links if l["text"].strip().lower() == item["link_text"].strip().lower()), None)
        if not original:
            continue

        href = original["href"].strip()
        if href.startswith("http"):
            final_url = href
        else:
            final_url = base_url.rstrip("/") + "/" + href.lstrip("/")

        sitelinks.append({
            "sitelink_text": original["text"][:25],
            "description_one": item["description_one"][:35],
            "description_two": item["description_two"][:35],
            "final_url": final_url
        })

    return sitelinks