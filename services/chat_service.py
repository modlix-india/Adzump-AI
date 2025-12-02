
import uuid

from datetime import datetime, timezone
from fastapi.responses import JSONResponse



from services.openai_client import chat_completion
from services.session_manager import sessions, SESSION_TIMEOUT
from utils.prompt_loader import load_prompt
from utils.helpers import get_today_end_date_with_duration
from models.campaign_data_model import CampaignData
from tools.account_selection_tool import (
    HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA,  
    execute_handle_account_selection,
)
from tools.tool_exe import (
    process_tool_call,
    validate_and_extract_fields,
    SAVE_CAMPAIGN_TOOL_SCHEMA,
    CONFIRM_CAMPAIGN_TOOL_SCHEMA, 
    safe_args
)

TODAY = datetime.now().strftime("%Y-%m-%d")

# Helpers — schema & progress

def get_required_fields():
    """Dynamically get required fields from CampaignData model."""
    # Only fields that must be present before confirmation
    return [field for field in CampaignData.model_fields.keys()]

def get_trackable_fields(collected_data):
    """Get fields that should be tracked for progress, excluding date fields."""
    return {k: True for k in collected_data.keys() if k not in ["startDate", "endDate"]}

def calculate_progress(collected_data):
    """Calculate collection progress dynamically."""
    required = get_required_fields()
    trackable = get_trackable_fields(collected_data)
    # count only required fields that are present, not derived fields
    # present = sum(1 for field in required if field in collected_data)
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
        "loginCustomerId": "Manager (MCC)",
        "customerId": "Customer ",
    }

    for field, label in field_labels.items():
        if field in collected_data:
            value = collected_data[field]
            if field == "budget":
                value = f"₹{int(float(value)):,}"
            elif field == "durationDays":
                value = f"{value} days"
            lines.append(f"- {label}: {value}")

    lines.append("Please confirm if everything is correct.")
    return "\n".join(lines)





def build_response(status: str, session: dict, ai_message: str, **kwargs) -> JSONResponse:
    """Build standardized JSON response with mask during collection and values at confirm."""
    collected_data = session.get("campaign_data", {})
    progress = calculate_progress(collected_data)

    # Show actual values only when awaiting_confirmation; otherwise show mask (true flags)
    if status == "awaiting_confirmation":
        payload_collected = collected_data
    else:
        trackable_fields = get_trackable_fields(collected_data)
        payload_collected = trackable_fields if trackable_fields else None

    response_data = {
        "status": status,
        "reply": ai_message or "",
        "collected_data": payload_collected,
        "progress": progress,
    }
    response_data.update(kwargs)
    return JSONResponse(content=response_data)

# System prompt

system_prompt_template = load_prompt("chat_service_prompt.txt")
SYSTEM_PROMPT = system_prompt_template.format(TODAY=TODAY)

# Confirmation-state handler

async def handle_confirmation_state(session: dict) -> JSONResponse:
    """Handle awaiting_confirmation state logic."""
    tools = [
        # Both tools must be wrapped in {"type":"function","function": ...}
        CONFIRM_CAMPAIGN_TOOL_SCHEMA,  # already wrapped in tool_exe.py
        {"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA},
        {"type": "function", "function": HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA},
    ]

    try:
        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500,
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls
    ai_message = response_message.content or ""
    

    
    if tool_calls:
        for tool_call in tool_calls:
            # User confirmed - complete campaign
            if tool_call.function.name == CONFIRM_CAMPAIGN_TOOL_SCHEMA["function"]["name"]:
                session["status"] = "completed"
                dates = get_today_end_date_with_duration(int(session["campaign_data"]["durationDays"]))
                session["campaign_data"].update(dates)

                return JSONResponse(
                    content={
                        "status": "completed",
                        "data": session["campaign_data"],
                    }
                )

            # User wants to change something (business fields)
            elif tool_call.function.name == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                try:
                    function_args = safe_args(tool_call.function.arguments)
                    valid_data, failed_fields, user_messages = await validate_and_extract_fields(function_args)

                    if valid_data:
                        session["campaign_data"].update(valid_data)

                    if user_messages:
                        ai_message = " ".join(user_messages)

                except Exception:
                    ai_message = "Could you please rephrase that?"
    
                summary = build_summary(session["campaign_data"])
                full_message = f"{ai_message}\n\n{summary}" if ai_message else summary
                session["chat_history"].append({"role": "assistant", "content": full_message})

                return build_response("awaiting_confirmation", session, full_message)
            
            elif tool_call.function.name == HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA["name"]:
                # Extract args the model passed and then server-execute the unified executor.
                args = safe_args(tool_call.function.arguments)
                action = args.get("action")
                login_customer_id = args.get("login_customer_id")
                retry = int(args.get("retry", 1))

                
                client_code = session.get("client_code")

                # If model asked to list customers for a login_customer_id, we may want to persist loginCustomerId
                # only if the model explicitly passed login_customer_id and action == "customer"
                if action == "customer" and login_customer_id:
                    # persist the confirmed MCC so collected_data reflects it
                    session["campaign_data"]["loginCustomerId"] = login_customer_id

                
                ai_message = await execute_handle_account_selection(session, action, client_code, login_customer_id=login_customer_id, retry=retry)

              
                session["chat_history"].append({"role": "assistant", "content": ai_message})
                return build_response("in_progress", session, ai_message)
            
    # User rejected or unclear - go back to in_progress
    session["status"] = "in_progress"
    ai_message = ai_message or "What would you like to change?"
    session["chat_history"].append({"role": "assistant", "content": ai_message})

    return build_response("in_progress", session, ai_message)


#Data-collection state handler
async def handle_data_collection_state(session: dict, client_code:str) -> JSONResponse:


    # Expose only the tools the model may call directly.
    tools = [
        {"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA},
        {"type": "function", "function": HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA},
    ]

    try:
        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500,
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls
    ai_message = response_message.content or ""


    # Process tool calls (business extraction + unified accounts discovery)
    if tool_calls:
        for tool_call in tool_calls:
            fname = tool_call.function.name

            if fname == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                # Business fields extraction/validation
                ai_message ,_ = await process_tool_call(session, tool_call, response_message)
                
            elif fname == HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA["name"]:
                # If model requests handle_account_selection explicitly, route to server executor
                function_args  = safe_args(tool_call.function.arguments)
                action = function_args .get("action")
                login_customer_id = function_args .get("login_customer_id")
                retry = function_args .get("retry", 1)
               
                # If the assistant asked for customers under a specific MCC, treat that as confirming the MCC.
                if action == "customer" and login_customer_id:
                    # Persist the confirmed MCC so collected_data reflects it.
                    session["campaign_data"]["loginCustomerId"] = login_customer_id
                ai_message = await execute_handle_account_selection(session, action, client_code, login_customer_id=login_customer_id, retry=retry)

    
    # Add AI response to history
    session["chat_history"].append({"role": "assistant", "content": ai_message})

    collected_data = session.get("campaign_data", {})
    
    # If all data collected (including IDs), proceed to confirmation
    if all_fields_collected(collected_data):
        session["status"] = "awaiting_confirmation"
        summary = build_summary(collected_data)
        session["chat_history"].append({"role": "assistant", "content": summary})
        return build_response("awaiting_confirmation", session, summary)

    # Still collecting data
    return build_response("in_progress", session, ai_message)

# Session management
async def start_session():
    """Initialize a new chat session."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "chat_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "last_activity": datetime.now(timezone.utc),
        "campaign_data": {},
        "status": "in_progress",
        # Option caches populated by Google tools:
        "mcc_options": [],
        "customer_options": [],
        # optional: store client_code provided by backend
        "client_code": None,
    }
    return {"session_id": session_id, "message": "New session started."}

async def process_chat(session_id: str, message: str, client_code: str):
    """Process chat message and manage conversation state."""
    # Validate session
    if session_id not in sessions:
        return JSONResponse(
            content={"status": "error", "message": "Invalid or expired session."},
            status_code=401,
        )

    session = sessions[session_id]
    current_time = datetime.now(timezone.utc)

    # Update stored client_code if provided by caller
    if client_code:
        session["client_code"] = client_code

    # Check session timeout
    if current_time - session["last_activity"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return JSONResponse(
            content={"status": "error", "message": "Session expired."},
            status_code=401,
        )

    # Update activity timestamp and chat history
    session["last_activity"] = current_time
    session["chat_history"].append({"role": "user", "content": message})

    # Route by status:
    session_status = session.get("status", "in_progress")

    if session_status == "awaiting_confirmation":
        return await handle_confirmation_state(session)
    else:
        return await handle_data_collection_state(session, client_code)

async def end_session(session_id: str):
    """End and cleanup a chat session."""
    if session_id not in sessions:
        return JSONResponse(status_code=404, content={"error": "Invalid session_id"})

    del sessions[session_id]
    return {"message": f"Session {session_id} ended successfully."}
