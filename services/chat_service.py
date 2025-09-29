import json, uuid, requests, re
from datetime import datetime, timezone, timedelta
from fastapi.responses import JSONResponse
from services.openai_client import chat_completion
from services.session_manager import sessions

SESSION_TIMEOUT = timedelta(minutes=30)
TODAY = datetime.now().strftime("%Y-%m-%d")

SYSTEM_PROMPT = f"""
You are an Advertising Campaign Assistant AI.
Your job is to collect all details required to create an ad campaign.

Rules:
1. Only process advertising-related requests.
2. If the prompt is unrelated, reply exactly:
   "I can only help with advertising-related campaign creation tasks."
   and stop.
3. If the user greets you (e.g., "hi", "hello", "hey"), reply with:
   "Hi. How can I help you?" and do not assume any campaign details yet.
4. Collect the following four details ONLY:
   - businessName
   - websiteURL (must be a valid http/https URL)
   - budget (accept only numbers, e.g., "5000")
   - durationDays (number of days to run the campaign)
5. If the user provides ALL details at once:
   - Validate each field using the rules below.
   - If everything is valid, show the user the complete summary and ask:
     "Please confirm if everything is correct (yes/no)."
6. If the user provides details one by one:
   - After each field, respond with TWO things:
     a) A JSON object containing only the field you just captured.
     b) A follow-up question asking for the next missing detail.
7. Validation rules for budget:
   - Accept only numbers (like "5000" or "20000").
   - Do NOT accept text like "five thousand".
8. Validation rules for websiteURL:
   - Must start with http:// or https://
   - If invalid, ask the user again until they provide a valid URL.
9. When a user provides duration, always respond with a JSON like:
   {{ "durationDays": 7 }}
   (replace 7 with the actual number of days provided by user).
10. After you collect all four fields (either step by step or all at once),
    always show the user a summary of the details
    AND end with this exact sentence (do not change wording at all):
    "Please confirm if everything is correct (yes/no)."
11. If user confirms with "yes", output ONLY the final JSON and end.
12. If user says "no", ask them what needs to be corrected and then continue.

Expected Final JSON Format:
{{
  "businessName": "Bakery",
  "websiteURL": "https://example.com",
  "budget": "5000",
  "startDate": "2025-09-11",
  "endDate": "2025-09-16"
}}
"""


def start_session():
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "chat_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "last_activity": datetime.now(timezone.utc),
        "campaign_data": {}
    }
    return {"session_id": session_id, "message": "New session started."}


async def process_chat(session_id: str, message: str):

    if session_id not in sessions:
        return JSONResponse(content={"status": "error", "message": "Invalid or expired session."}, status_code=400)

    session = sessions[session_id]

    # Expiry check
    if datetime.now(timezone.utc) - session["last_activity"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return JSONResponse(content={"status": "error", "message": "Session expired."}, status_code=400)

    session["last_activity"] = datetime.now(timezone.utc)
    session["chat_history"].append({"role": "user", "content": message})

    # Call OpenAI
    ai_message = await chat_completion(session["chat_history"])

    collected_data = session.get("campaign_data", {})
    collected_this_turn = None
    pure_reply = ai_message

    # Extract JSON if present
    json_match = re.search(r"\{.*?\}", ai_message, re.DOTALL)
    if json_match:
        try:
            new_data = json.loads(json_match.group())
            if isinstance(new_data, dict):
                # Convert durationDays to startDate & endDate
                if "durationDays" in new_data:
                    try:
                        days = int(new_data["durationDays"])
                        start_date = datetime.now().date()
                        print("Python datetime.now():", datetime.now())
                        print("Python datetime.now(timezone.utc):", datetime.now(timezone.utc))
                        end_date = start_date + timedelta(days=days)
                        new_data["startDate"] = start_date.strftime("%Y-%m-%d")
                        new_data["endDate"] = end_date.strftime("%Y-%m-%d")
                        # new_data.pop("durationDays", None)
                    except ValueError:
                        pass
                # Changed: always merge into collected_data
                collected_data.update(new_data)
                session["campaign_data"] = collected_data
                collected_this_turn = new_data
            pure_reply = ai_message.replace(json_match.group(), "").strip()
        except json.JSONDecodeError:
            pass

    session["chat_history"].append({"role": "assistant", "content": ai_message})

    # Build collected_data with True values (for progress)
    masked_data = {k: True for k in collected_data.keys()}

    # Final confirmation step
    if "Please confirm if everything is correct" in ai_message:
        return JSONResponse(content={
            "status": "awaiting_confirmation",
            "reply": pure_reply,
            "collected_data": masked_data if masked_data else None,
            "progress": f"{len(masked_data)}/4"
        })

    # CHANGED SECTION: Final JSON from AI (confirmation completed)
    if ai_message.strip().startswith("{") and ai_message.strip().endswith("}"):
        try:
            parsed = json.loads(ai_message)

            # Merge instead of overwriting
            final_data = {**session.get("campaign_data", {}), **parsed}

            # Convert durationDays if still present
            if "startDate" in final_data or "endDate" in final_data or "durationDays" in final_data:
                try:
                    days = int(final_data.get("durationDays", 7))  # fallback 7 days
                    start_date = datetime.now().date()
                    end_date = start_date + timedelta(days=days)
                    final_data["startDate"] = start_date.strftime("%Y-%m-%d")
                    final_data["endDate"] = end_date.strftime("%Y-%m-%d")
                    final_data.pop("durationDays", None)
                except ValueError:
                    pass

            session["campaign_data"] = final_data
            return JSONResponse(content={"status": "completed", "data": final_data})

        except json.JSONDecodeError:
            return JSONResponse(content={"status": "error", "message": "Invalid JSON from AI"})

    # Normal response
    response = {
        "status": "in_progress",
        "reply": pure_reply,
        "collected_data": masked_data if masked_data else None,
        "progress": f"{len(masked_data)}/4"
    }

    return JSONResponse(content=response)


def end_session(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Invalid session_id"})

    campaign_data = session.get("campaign_data")
    if campaign_data:
        try:
            response = requests.post(
                "http://localhost:8000/ai-suggestions",
                json={"campaign_data": campaign_data}
            )
            print("AI Suggestions Response:", response.json())
        except Exception as e:
            print(f"Error calling /ai-suggestions: {e}")

    del sessions[session_id]
    return {"message": f"Session {session_id} ended."}
