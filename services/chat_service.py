import json, uuid
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
from typing import Optional

from services.openai_client import chat_completion
from services.session_manager import sessions, SESSION_TIMEOUT
from utils.prompt_loader import load_prompt
from utils.helpers import get_today_end_date_with_duration
from models.campaign_data_model import CampaignData
from tools.tool_exe import process_tool_call, SAVE_CAMPAIGN_TOOL_SCHEMA, CONFIRM_CAMPAIGN_TOOL_SCHEMA, validate_and_extract_fields


TODAY = datetime.now().strftime("%Y-%m-%d")

# HELPER FUNCTIONS - SCHEMA & PROGRESS
def get_required_fields():
    """Dynamically get required fields from CampaignData model."""
    return [field for field in CampaignData.model_fields.keys()]


def get_trackable_fields(collected_data):
    """Get fields that should be tracked for progress, excluding date fields."""
    return {k: True for k in collected_data.keys() if k not in ["startDate", "endDate"]}


def calculate_progress(collected_data):
    """Calculate collection progress dynamically."""
    required = get_required_fields()
    trackable = get_trackable_fields(collected_data)
    return f"{len(trackable)}/{len(required)}"


def all_fields_collected(collected_data):
    """Check if all required fields are collected."""
    required = get_required_fields()
    return all(field in collected_data for field in required)


def build_summary(collected_data):
    """Build confirmation summary dynamically from collected data."""
    lines = ["I have the following details for your campaign:"]
    
    field_labels = {
        "businessName": "Business Name",
        "websiteURL": "Website",
        "budget": "Budget",
        "durationDays": "Duration",
        "loginCustomerId": "Customer ID"
    }
    
    for field, label in field_labels.items():
        if field in collected_data:
            value = collected_data[field]
            if field == "budget":
                value = f"₹{value}"
            elif field == "durationDays":
                value = f"{value} days"
            lines.append(f"- {label}: {value}")
    
    lines.append("\nPlease confirm if everything is correct.")
    return "\n".join(lines)


# HELPER FUNCTIONS - RESPONSE BUILDING
def build_response(status: str, session: dict, ai_message: str = None, **kwargs) -> JSONResponse:
    """Build standardized JSON response."""
    collected_data = session.get("campaign_data", {})
    trackable_fields = get_trackable_fields(collected_data)
    progress = calculate_progress(collected_data)
    
    response_data = {
        "status": status,
        "reply": ai_message or "",
        "collected_data": collected_data if status == "awaiting_confirmation" else (trackable_fields if trackable_fields else None),
        "progress": progress
    }
    
    response_data.update(kwargs)
    return JSONResponse(content=response_data)


# SYSTEM PROMPT
system_prompt_template = load_prompt("chat_service_prompt.txt")
SYSTEM_PROMPT = system_prompt_template.format(TODAY=TODAY)

# STATE HANDLERS
async def handle_confirmation_state(session: dict) -> JSONResponse:
    """Handle awaiting_confirmation state logic."""
    tools = [CONFIRM_CAMPAIGN_TOOL_SCHEMA, {"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA}]
    
    try:
        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls
    ai_message = response_message.content or ""

    if tool_calls:
        for tool_call in tool_calls:
            # User confirmed - complete campaign
            if tool_call.function.name == "confirm_campaign_creation":
                session["status"] = "completed"
                dates = get_today_end_date_with_duration(int(session["campaign_data"]["durationDays"]))
                session["campaign_data"].update(dates)
                
                return JSONResponse(content={
                    "status": "completed",
                    "data": session["campaign_data"]
                })
            
            # User wants to change something
            elif tool_call.function.name == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                try:
                    function_args = json.loads(tool_call.function.arguments)
                    valid_data, failed_fields, user_messages = await validate_and_extract_fields(
                        function_args
                    )
                    
                    if valid_data:
                        session["campaign_data"].update(valid_data)
                    
                    if user_messages:
                        ai_message = " ".join(user_messages)
                    
                except json.JSONDecodeError:
                    ai_message = "Could you please rephrase that?"
                
                summary = build_summary(session["campaign_data"])
                full_message = f"{ai_message}\n\n{summary}" if ai_message else summary
                session["chat_history"].append({"role": "assistant", "content": full_message})
                
                return build_response("awaiting_confirmation", session, full_message)

    # User rejected or unclear - go back to in_progress
    session["status"] = "in_progress"
    ai_message = ai_message or "What would you like to change?"
    session["chat_history"].append({"role": "assistant", "content": ai_message})
    
    return build_response("in_progress", session, ai_message)


async def process_google_login_customer_id(session: dict, login_customer_id: str = None) -> Optional[JSONResponse]:
    """Processes and validates the Google Login Customer ID."""

    if login_customer_id and not session["campaign_data"].get("loginCustomerId"):
        valid_id_data, _, _ = await validate_and_extract_fields(
            {"loginCustomerId": login_customer_id}
        )

        if valid_id_data.get("loginCustomerId"):
            session["campaign_data"].update(valid_id_data)
        else:
            return JSONResponse(
                content={"status": "error", "message": "Invalid customer ID. Please provide a 10-digit customer ID."},
                status_code=400
            )
    return None

async def handle_data_collection_state(session: dict, login_customer_id: str = None) -> JSONResponse:
    """Handle in_progress (data collection) state logic."""
    
    # Handle login customer ID from header/param
    error_response = await process_google_login_customer_id(session, login_customer_id)
    if error_response:
        return error_response

    tools = [{"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA}]
    
    try:
        # First AI call to extract data
        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls
    ai_message = response_message.content or ""

    # Process tool calls
    if tool_calls:
        for tool_call in tool_calls:
            if tool_call.function.name == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                ai_message, _ = await process_tool_call(session, tool_call, response_message)

    # Add AI response to history
    session["chat_history"].append({"role": "assistant", "content": ai_message})
    
    collected_data = session.get("campaign_data", {})

    # Check if all data collected
    if all_fields_collected(collected_data):
        session["status"] = "awaiting_confirmation"
        summary = build_summary(collected_data)
        session["chat_history"].append({"role": "assistant", "content": summary})
        
        return build_response("awaiting_confirmation", session, summary)

    # Still collecting data
    return build_response("in_progress", session, ai_message)


# SESSION MANAGEMENT
async def start_session():
    """Initialize a new chat session."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "chat_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "last_activity": datetime.now(timezone.utc),
        "campaign_data": {},
        "status": "in_progress"
    }
    return {"session_id": session_id, "message": "New session started."}


async def process_chat(session_id: str, message: str, login_customer_id: str = None):
    """Process chat message and manage conversation state."""
    
    # Validate session
    if session_id not in sessions:
        return JSONResponse(
            content={"status": "error", "message": "Invalid or expired session."},
            status_code=401
        )

    session = sessions[session_id]
    current_time = datetime.now(timezone.utc)

    # Check session timeout
    if current_time - session["last_activity"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return JSONResponse(
            content={"status": "error", "message": "Session expired."},
            status_code=401
        )

    # Update activity timestamp
    session["last_activity"] = current_time
    session["chat_history"].append({"role": "user", "content": message})

    # Route to appropriate state handler
    session_status = session.get("status", "in_progress")
    
    if session_status == "awaiting_confirmation":
        return await handle_confirmation_state(session)
    else:
        return await handle_data_collection_state(session, login_customer_id)


async def end_session(session_id: str):
    """End and cleanup a chat session."""
    if session_id not in sessions:
        return JSONResponse(
            status_code=404,
            content={"error": "Invalid session_id"}
        )
    
    del sessions[session_id]
    return {"message": f"Session {session_id} ended successfully."}