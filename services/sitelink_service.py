from fastapi import HTTPException
from typing import List, Dict, Any
from urllib.parse import urlparse
import json
import re

from services.openai_client import chat_completion  # ✅ Using your OpenAI client


# ---------------- Helper: Check if link is internal ---------------- #
def is_internal_link(href: str, base_domain: str) -> bool:
    """Return True if href belongs to the same domain, subdomain, or is relative."""
    if not href or href.startswith(("javascript:void(0)", "tel:")):
        return False

    parsed = urlparse(href)
    if not parsed.netloc:  # relative or hash (#gallery, /about)
        return True

    href_domain = parsed.netloc.replace("www.", "").lower()
    return base_domain in href_domain


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

    # Step 2: Prepare the LLM prompt
    prompt = f"""
You are an expert Google Ads strategist and copywriter who specializes in creating high-performing sitelinks that drive conversions and leads.

### INPUT:
1. Short **summary** of the website/business
2. **Internal links** JSON (each with `text` and `href`)
3. **Base URL**

### TASK:
- Analyze each link’s **text** vs **summary**.
- Prioritize links by semantic similarity and lead-generation intent:
  - **High priority** → strongly aligned with summary and conversion-focused
  - **Medium priority** → moderately aligned
  - **Low priority** → weakly aligned or generic
- Ensure **final sitelinks cover diverse sections**: products, services, promotions, contact, resources, etc.
- Include up to **15 sitelinks**.
  - If high + medium < 15, fill remaining slots with **relevant low-priority links**.
- Skip irrelevant pages: "Privacy Policy", "Careers", "Login", "Terms", etc.

### FINAL URL HANDLING (CRITICAL)
- For each link:
    - Use the `href` from internal links JSON as **final_url exactly as-is**.
        - If it starts with `http`, `https`, `tel`, or `#` → use it exactly.
        - If it is relative → prepend `base_url + "/"` exactly as given.
    - ⚠️ Do **not** modify href in any way, do **not** generate readable slugs, do **not** use sitelink text to replace href.
    - Skip links with empty `text` or invalid href (e.g., `javascript:void(0)`).

### GENERATION RULES:
- `sitelink_text`: ad-friendly, max 25 chars
- `description_1`: persuasive benefit, ≤ 35 chars
- `description_2`: supportive motivation/CTA, ≤ 35 chars
- Ensure **high CTR and lead generation**
- Focus on **relevance, diversity, and conversion potential**

### PRIORITIZATION LOGIC:
- Classify links as high/medium/low based on semantic similarity to summary.
- Prefer **high + medium priority** links. Include low only if total links < 15.
- Ensure links cover **different site sections**, avoiding repetition.

### TONE:
- Conversational, persuasive, brand-consistent

### INPUT DATA:
Summary:
{summary}

Base URL:
{base_url}

Internal Links:
{json.dumps(valid_links, indent=2)}

### OUTPUT:
- Maximum **15 sitelinks**
- Only valid JSON
- Ensure diversity, conversion focus, and correct final URLs

### EXAMPLE EXPECTED OUTPUT (use exact hrefs):
[
  {{
    "sitelink_text": "master plan",
    "description_1": "Explore our master plan",
    "description_2": "See full layout details",
    "final_url": "https://cityville.in/#4c1DnNMRQldZKTwDq8KWnF:-100"
  }},
  {{
    "sitelink_text": "gallery",
    "description_1": "View stunning images",
    "description_2": "Visualize your new home",
    "final_url": "https://cityville.in/#uQ54sl6LCuWshnrep2zcl:-100"
  }},
  {{
    "sitelink_text": "amenities",
    "description_1": "Check our luxury amenities",
    "description_2": "Experience top facilities",
    "final_url": "https://cityville.in/#1IRHQ14ZOhLjvlFrNC9Twg:-100"
  }}
]
"""

    


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
