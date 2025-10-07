import json, uuid, requests, re
from datetime import datetime, timezone, timedelta
from fastapi.responses import JSONResponse
from services.openai_client import chat_completion
from services.session_manager import sessions
from utils.prompt_loader import load_prompt

SESSION_TIMEOUT = timedelta(minutes=30)
TODAY = datetime.now().strftime("%Y-%m-%d")

system_prompt_template = load_prompt("chat_service_prompt.txt")
SYSTEM_PROMPT = system_prompt_template.format(TODAY=TODAY)

def start_session():
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "chat_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "last_activity": datetime.now(timezone.utc),
        "campaign_data": {}
    }
    return {"session_id": session_id, "message": "New session started."}


def extract_json_from_response(ai_message):
    jsons = []
    clean_message = ai_message

    for match in re.finditer(r'\{[^{}]*\}', ai_message):
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                jsons.append(parsed)
                clean_message = clean_message.replace(match.group(), '', 1)
        except json.JSONDecodeError:
            continue

    return jsons, clean_message.strip()


def validate_and_clean_data(data: dict):

    validated_data = {}
    url_regex = re.compile(r'^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)')
    
    for key, value in data.items():
        if key == "websiteURL":
            if isinstance(value, str) and url_regex.match(value):
                validated_data[key] = value
        elif key == "budget":
            if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                validated_data[key] = str(value)
        elif key == "durationDays":
            if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                validated_data[key] = int(value)
        elif key == "businessName":
            if isinstance(value, str) and value:
                validated_data[key] = value
        elif key == "login-customer-id":
            if isinstance(value, str):
                validated_data[key] = value.replace("-", "")
    return validated_data



async def process_chat(session_id: str, message: str, login_customer_id: str = None):

    if session_id not in sessions:
        return JSONResponse(
            content={"status": "error", "message": "Invalid or expired session."},
            status_code=400
            )

    session = sessions[session_id]

    # If login_customer_id is provided, add it to the message and save to session.
    if login_customer_id:
        session["campaign_data"]["login-customer-id"] = login_customer_id.replace("-", "")
        message = f"{message} (My customer id is {login_customer_id})"

    # Expiry check
    if datetime.now(timezone.utc) - session["last_activity"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return JSONResponse(
            content={"status": "error", "message": "Session expired."},
            status_code=400
            )

    session["last_activity"] = datetime.now(timezone.utc)
    session["chat_history"].append({"role": "user", "content": message})

    # Call OpenAI
    ai_message = await chat_completion(session["chat_history"])
    
    extracted_jsons,pure_reply = extract_json_from_response(ai_message)

    collected_data = session.get("campaign_data", {})

    # process the extracted Json
    validated_data = {}
    for new_data in extracted_jsons:
        validated_data.update(validate_and_clean_data(new_data))

    # Update session with only validated data
    collected_data.update(validated_data)

    # Special handling for duration to calculate end date
    if "durationDays" in validated_data:
        try:
            days = int(validated_data["durationDays"])
            start_date = datetime.now().date()
            end_date = start_date + timedelta(days=days)
            collected_data["startDate"] = start_date.strftime("%Y-%m-%d")
            collected_data["endDate"] = end_date.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    session["campaign_data"] = collected_data
    session["chat_history"].append({"role":"assistant","content":ai_message})

    # Build collected_data with True values (for progress)
    masked_data = {k: True for k in collected_data.keys() if k not in ["startDate", "endDate"]}

    # Final confirmation step
    if "Please confirm if everything is correct" in ai_message:
        return JSONResponse(content={
            "status": "awaiting_confirmation",
            "reply": pure_reply,
            "collected_data": masked_data if masked_data else None,
            "progress": f"{len(masked_data)}/5"
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
        "progress": f"{len(masked_data)}/5"
    }

    return JSONResponse(content=response)


async def end_session(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"error": "Invalid session_id"})
    
    if session_id in sessions:
        del sessions[session_id]
    return {"message": f"Session {session_id} ended."}