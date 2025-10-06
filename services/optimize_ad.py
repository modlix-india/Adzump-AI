import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI
from typing import List, Dict, Any

# Load .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# Helpers for location logic
# ---------------------------

def is_valid_geo_target(obj: Dict[str, Any]) -> bool:
    try:
        g = obj.get("geoTargetConstant") if isinstance(obj, dict) else None
        return bool(g and g.get("id") and g.get("name"))
    except Exception:
        return False

def geo_id_name(gobj: Dict[str, Any]):
    g = gobj.get("geoTargetConstant", {})
    return str(g.get("id")), g.get("name")

def choose_fallback_locations(original_locations: List[Dict[str, Any]], n: int = 3) -> List[Dict[str, Any]]:
    """
    Heuristic fallback:
    - Prioritize original locations if they appear in priority list.
    - Fill remaining slots from generic strong markets if missing.
    - Returns up to n geoTargetConstant-wrapped location dicts.
    """
    priority_names = ["Bengaluru", "Indiranagar", "Hyderabad", "Chennai", "Coimbatore", "Mysore"]
    chosen = []
    seen_ids = set()

    # Step 1: keep originals that match priority list
    for name in priority_names:
        for loc in original_locations:
            if not is_valid_geo_target(loc):
                continue
            _, loc_name = geo_id_name(loc)
            if loc_name and name.lower() in loc_name.lower():
                loc_id, _ = geo_id_name(loc)
                if loc_id not in seen_ids:
                    chosen.append(loc)
                    seen_ids.add(loc_id)
                if len(chosen) >= n:
                    return chosen

    # Step 2: add other valid originals
    for loc in original_locations:
        if not is_valid_geo_target(loc):
            continue
        loc_id, _ = geo_id_name(loc)
        if loc_id not in seen_ids:
            chosen.append(loc)
            seen_ids.add(loc_id)
        if len(chosen) >= n:
            return chosen

    # Step 3: add generic fallback candidates
    generic_candidates = [
        {"geoTargetConstant": {"id": "1019234", "name": "Hyderabad", "countryCode": "IN", "targetType": "City"}},
        {"geoTargetConstant": {"id": "1007770", "name": "Mysore", "countryCode": "IN", "targetType": "City"}},
        {"geoTargetConstant": {"id": "1029931", "name": "Coimbatore", "countryCode": "IN", "targetType": "City"}}
    ]
    for cand in generic_candidates:
        cid, _ = geo_id_name(cand)
        if cid not in seen_ids:
            chosen.append(cand)
            seen_ids.add(cid)
        if len(chosen) >= n:
            break

    return chosen

def finalize_locations(full_payload: dict, optimized_payload: dict) -> None:
    """
    - If optimized_payload.basicData.locations is valid (2–3 entries), keep it.
    - Otherwise, choose fallback locations.
    """
    basic_orig = full_payload.get("basicData", {})
    orig_locations = basic_orig.get("locations", []) or []
    basic_opt = optimized_payload.get("basicData", {})
    opt_locations = basic_opt.get("locations", [])

    # count valid optimized locations
    valid_opt_locs = [l for l in (opt_locations or []) if is_valid_geo_target(l)]
    if 2 <= len(valid_opt_locs) <= 3:
        # deduplicate
        unique = []
        ids = set()
        for l in valid_opt_locs:
            lid, _ = geo_id_name(l)
            if lid not in ids:
                ids.add(lid)
                unique.append(l)
        basic_opt["locations"] = unique[:3]
        optimized_payload["basicData"] = basic_opt
        return

    # fallback
    fallback = choose_fallback_locations(orig_locations, n=3)
    if fallback:
        basic_opt["locations"] = fallback
        optimized_payload["basicData"] = basic_opt
        return

    # last resort: keep first 1–3 valid originals
    keep = []
    for l in orig_locations:
        if is_valid_geo_target(l):
            keep.append(l)
        if len(keep) >= 3:
            break
    basic_opt["locations"] = keep
    optimized_payload["basicData"] = basic_opt

# ---------------------------
# Core LLM service
# ---------------------------

def clean_llm_json(raw_text: str) -> str:
    """
    Cleans LLM output by removing code fences and extra whitespace.
    """
    cleaned = re.sub(r"```json|```", "", raw_text, flags=re.IGNORECASE).strip()
    return cleaned

def optimize_with_llm(full_payload: dict):
    """
    Sends campaign payload to LLM and returns optimized JSON response.
    Enforces limits for headlines/descriptions and validates locations.
    """
    prompt = f"""
    You are a Google Ads optimization expert.

    Your job is to take the given campaign JSON payload and return an optimized version.
    ⚠️ Rules:
    - Keep the JSON structure and keys identical.
    - Return only valid JSON (no markdown, no comments).
    - All text fields must strictly follow Google Ads limits.

    Optimization tasks:
    1. **Budget** → update to a realistic, optimized budget value based on performance.  
    2. **Metrics** → adjust/improve (cost, clicks, impressions, conversions) to realistic values.  
    3. **Locations** → optimize targeting:
   - Always refine the list of locations.
   - Keep only the top 2–3 high-performing locations from input.
   - Remove all locations with low/zero conversions.
   - Ensure each location has a valid `geoTargetConstant` structure.
   - Always add at least 1 and up to 3 nearby strong market locations 
     (e.g., Whitefield `geoTargetConstant/1028917`, Marathahalli `geoTargetConstant/1028796`, Koramangala `geoTargetConstant/1028921`).
    4. **Age** → refine audience age ranges to improve performance.  
    5. **Gender** → adjust targeting balance for better reach.  
    6. **Headlines** → rewrite professional, compelling ad headlines (≤30 characters) that grab attention, create urgency, and highlight strong value. Avoid spammy tone.  
    7. **Descriptions** → rewrite professional, persuasive ad descriptions (≤90 characters) that engage users, build trust, and encourage early purchase or sign-up.  

    Input JSON:
    {json.dumps(full_payload, indent=2)}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.choices[0].message.content
    cleaned_content = clean_llm_json(content)

    try:
        optimized = json.loads(cleaned_content)

        # Ensure structure exists
        if "basicData" not in optimized:
            optimized["basicData"] = {}

        # Validate & finalize locations
        finalize_locations(full_payload, optimized)

        return optimized.get('basicData',{})
    except json.JSONDecodeError:
        return {
            "error": "LLM response could not be parsed as JSON",
            "raw": cleaned_content
        }
