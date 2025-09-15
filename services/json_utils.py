import json
import re

def safe_json_parse(raw_output: str):
    """Remove markdown code fences and parse JSON safely."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_output.strip(), flags=re.DOTALL)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON", "raw_output": raw_output}
