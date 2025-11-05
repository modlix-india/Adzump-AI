import os
import json
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

THRESHOLD = 1000


def classify_search_terms(search_terms):
    classified_results = []

    for item in search_terms:
        searchterm = item.get("searchterm")
        metrics = item.get("metrics", {})
        raw_cpc = metrics.get("costPerConversion")

        # Convert micros → human-readable
        cost_per_conversion = (
            raw_cpc / 1_000_000 if raw_cpc is not None else None
        )

        # Apply your rule
        if cost_per_conversion is None:
            recommendation = "negative"
            reason = f"No conversion data for {searchterm}, marked negative."
        elif cost_per_conversion < THRESHOLD:
            recommendation = "positive"
            reason = f"Cost per conversion is ₹{cost_per_conversion:.2f}, below threshold ₹{THRESHOLD} — positive."
        else:
            recommendation = "negative"
            reason = f"Cost per conversion is ₹{cost_per_conversion:.2f}, above threshold ₹{THRESHOLD} — negative."

        # Keep metrics consistent
        metrics["costPerConversion"] = cost_per_conversion

        # Optional: Get LLM explanation
        prompt = f"""
You are a Google Ads expert. Here is a search term with metrics:
{json.dumps({'searchterm': searchterm, 'metrics': metrics}, indent=2, ensure_ascii=False)}

Python has classified it as {recommendation}.
Explain clearly in 1-2 sentences why this recommendation makes sense.
Important: Do NOT add quotes around the search term in your explanation.
Use INR currency symbol (₹). Return only the explanation.
"""
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            llm_reason = response.choices[0].message.content.strip()
            reason += " LLM: " + llm_reason
        except Exception as e:
            reason += " LLM: [failed to fetch explanation]"

        classified_results.append({
            "searchterm": searchterm,
            "metrics": metrics,
            "recommendation": recommendation,
            "reason": reason
        })

    return classified_results

