
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
    handle_account_selection_by_status
)
from tools.tool_exe import (
    process_tool_call,
    validate_and_extract_fields,
    SAVE_CAMPAIGN_TOOL_SCHEMA,
    CONFIRM_CAMPAIGN_TOOL_SCHEMA,
    safe_args
)
from structlog import get_logger    #type: ignore

TODAY = datetime.now().strftime("%Y-%m-%d")
logger = get_logger(__name__)

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

def all_business_fields_collected(collected_data):
    return all(
        field in collected_data
        for field in ["businessName", "websiteURL", "budget", "durationDays"]
    )


def build_summary(collected_data , session):
    """Build confirmation summary dynamically from collected data."""
    lines = ["I have the following details for your campaign:"]

    field_labels = {
        "businessName": "Business Name",
        "websiteURL": "Website",
        "budget": "Budget",
        "durationDays": "Duration",
        "loginCustomerId": "Manager (MCC)",
        "customerId": "Customer",
    }

    for field, label in field_labels.items():
        if field in collected_data:
            value = collected_data[field]
            if field == "budget":
                value = f"₹{int(float(value)):,}"
            elif field == "durationDays":
                value = f"{value} days"

            elif field == "loginCustomerId":
                mcc_name = None
                for mcc in session.get("mcc_options", []):
                    if str(mcc.get("id")) == str(value):
                        mcc_name = mcc.get("name")
                        break
                if mcc_name:
                    value = f"{mcc_name} ({value})"

            elif field == "customerId":
                customer_name = None
                for customer in session.get("customer_options", []):
                    if str(customer.get("id")) == str(value):
                        customer_name = customer.get("name")
                        break
                if customer_name:
                    value = f"{customer_name} ({value})"

            lines.append(f"- {label}: {value}")

    lines.append("Please confirm if everything is correct.")
    return "\n".join(lines)


def build_response(status: str, session: dict, ai_message: str, account_selection=None)-> JSONResponse:
    """Build standardized JSON response with mask during collection and values at confirm."""
    
    collected_data = session.get("campaign_data", {})
    progress = calculate_progress(collected_data)

    if status == "awaiting_confirmation":
        payload_collected = collected_data
    else:
        payload_collected = get_trackable_fields(collected_data)

    return JSONResponse(
        content={
            "status": status,
            "reply": ai_message or "",
            "collected_data": payload_collected,
            "progress": progress,
            "account_selection": account_selection,
        }
    )



system_prompt_template = load_prompt("chat_service_prompt.txt")
SYSTEM_PROMPT = system_prompt_template.format(TODAY=TODAY)

# Confirmation-state handler

async def handle_confirmation_state(session: dict) -> JSONResponse:
    """Handle awaiting_confirmation state logic."""
    tools = [
        CONFIRM_CAMPAIGN_TOOL_SCHEMA,
        {"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA},
        {"type": "function", "function": HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA},
    ]

    try:
        # Inject authoritative system state
        session["chat_history"] = [
            msg for msg in session["chat_history"]
            if not msg["content"].startswith("SYSTEM STATE")
        ]
        session["chat_history"].insert(
            1,
            {
                "role": "system",
                "content": f"SYSTEM STATE (AUTHORITATIVE): campaign_status = {session['status']}",
            },
        )

        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500,
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls or []
    ai_message = response_message.content or ""
    

    if tool_calls:
        for tool_call in tool_calls:
            name = tool_call.function.name

            # User confirmed - complete campaign
            if name == CONFIRM_CAMPAIGN_TOOL_SCHEMA["function"]["name"]:
                session["status"] = "completed"
                dates = get_today_end_date_with_duration(int(session["campaign_data"]["durationDays"]))
                session["campaign_data"].update(dates)
                session["campaign_data"]["budget"] = int(session["campaign_data"]["budget"])
                response_data = dict(session["campaign_data"])
                if "durationDays" in response_data:
                    duration = int(response_data["durationDays"])
                    response_data["durationDays"] = (
                        "1 Day" if duration == 1 else f"{duration} Days"
                    )
                    session["campaign_data"]["durationDays"] = response_data["durationDays"]
                # Manager (MCC)
                mcc_name = None
                if "loginCustomerId" in response_data:
                    mcc_id = response_data["loginCustomerId"]
                    for mcc in session.get("mcc_options", []):
                        if str(mcc.get("id")) == str(mcc_id):
                            mcc_name = mcc.get("name")
                            break
                if mcc_name:
                    response_data["loginCustomerName"] = mcc_name

                # Customer
                customer_name = None
                if "customerId" in response_data:
                    customer_id = response_data["customerId"]
                    for customer in session.get("customer_options", []):
                        if str(customer.get("id")) == str(customer_id):
                            customer_name = customer.get("name")
                            break
                if customer_name:
                    response_data["customerName"] = customer_name

                return JSONResponse(
                    content={
                        "status": "completed",
                        "data": response_data,
                    }
                )

            # User wants to change something (business fields)
            elif name == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                try:
                    args = safe_args(tool_call.function.arguments)
                    valid_data, _, user_messages = await validate_and_extract_fields(args)

                    if valid_data:
                        session["campaign_data"].update(valid_data)

                    if user_messages:
                        ai_message = " ".join(user_messages)

                except Exception:
                    ai_message = "Could you please rephrase that?"

                summary = build_summary(session["campaign_data"] , session)
                full_message = f"{ai_message}\n\n{summary}" if ai_message else summary
                session["chat_history"].append({"role": "assistant", "content": full_message})

                return build_response("awaiting_confirmation", session, full_message)

            elif name == HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA["name"]:
                args = safe_args(tool_call.function.arguments)
                action = args.get("action") or ""
                retry = int(args.get("retry", 1))
                client_code = session.get("client_code") or ""

                tool_result = await execute_handle_account_selection(
                    session,
                    action,
                    client_code,
                    retry=retry,
                )

                account_selection = None
                if tool_result.get("options"):
                    account_selection = {
                        "type": tool_result.get("selection_type"),
                        "options": tool_result.get("options"),
                    }

                return build_response(
                    session["status"],
                    session,
                    tool_result.get("message","") ,
                    account_selection=account_selection,
                )

    ai_message = ai_message or "What would you like to change?"
    session["chat_history"].append({"role": "assistant", "content": ai_message})
    # return build_response("in_progress", session, ai_message)
    return build_response("awaiting_confirmation", session, ai_message)


#Data-collection state handler
async def handle_data_collection_state(session: dict, client_code: str) -> JSONResponse:
    tools = [
        {"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA},
        {"type": "function", "function": HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA},
    ]

    try:
        # Inject authoritative system state
        session["chat_history"] = [
            msg for msg in session["chat_history"]
            if not msg["content"].startswith("SYSTEM STATE")
        ]
        session["chat_history"].insert(
            1,
            {
                "role": "system",
                "content": f"SYSTEM STATE (AUTHORITATIVE): campaign_status = {session['status']}",
            },
        )

        response = await chat_completion(session["chat_history"], tools=tools, tool_choice="auto")
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": f"AI service error: {str(e)}"},
            status_code=500,
        )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls or []
    ai_message = response_message.content or ""
    logger.info(tool_calls)
    logger.info(ai_message)
    # Process tool calls (business fields extraction + unified accounts discovery)
    if tool_calls:
        for tool_call in tool_calls:
            fname = tool_call.function.name

            if fname == SAVE_CAMPAIGN_TOOL_SCHEMA["name"]:
                # Business fields extraction/validation
                ai_message, _ = await process_tool_call(session, tool_call, response_message)
                if all_business_fields_collected(session["campaign_data"]):
                    session["status"] = "selecting_mcc"
                    tool_result = await execute_handle_account_selection(
                        session=session,
                        action="mcc",
                        client_code=client_code,
                    )
                    return build_response(
                        session["status"],
                        session,
                        tool_result.get("message",""),
                        account_selection={
                            "type": tool_result.get("selection_type"),
                            "options": tool_result.get("options"),
                    } if tool_result.get("options") else None,
                )

            elif fname == HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA["name"]:
                args = safe_args(tool_call.function.arguments)
                action = args.get("action") or ""
                retry = int(args.get("retry", 1))

                tool_result = await execute_handle_account_selection(session, action, client_code, retry=retry)
                logger.info(tool_result)

                account_selection = None
                if tool_result.get("options"):
                    account_selection = {
                        "type": tool_result.get("selection_type"),
                        "options": tool_result.get("options"),
                    }
                
                message = tool_result.get("message", "")
                return build_response(
                    session["status"],
                    session,
                    message,
                    account_selection=account_selection,
                )

    session["chat_history"].append({"role": "assistant", "content": ai_message})

    collected_data = session.get("campaign_data", {})

    # If all data collected (including IDs), proceed to confirmation
    if all_fields_collected(collected_data):
        session["status"] = "awaiting_confirmation"
        summary = build_summary(collected_data , session)
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
        "mcc_options": [],
        "customer_options": [],
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

    if current_time - session["last_activity"] > SESSION_TIMEOUT:
        del sessions[session_id]
        return JSONResponse(
            content={"status": "error", "message": "Session expired."},
            status_code=401,
        )

    # Update activity timestamp and chat history
    session["last_activity"] = current_time
    session["client_code"] = client_code

    if session.get("status") == "completed":
        return JSONResponse(
            content={
                "status": "completed",
                "reply": "Your campaign has already been completed. If you want to create a new campaign, please start a new session.",
                "collected_data": session.get("campaign_data", {}),
            "progress": calculate_progress(session.get("campaign_data", {})),
            "account_selection": None,
        }
    )

    if session["status"] in ("selecting_mcc", "selecting_customer"):
        result = await handle_account_selection_by_status(
            session=session,
            message=message,
            client_code=client_code,
        )

        session["status"] = result["next_status"]

        if result.get("requires_summary"):
            ai_message = build_summary(session["campaign_data"], session)
        else:
            ai_message = result.get("message", "")

        return build_response(
            status=session["status"],
            session=session,
            ai_message=ai_message,
            account_selection=result.get("selection"),
        )
    session["chat_history"].append({"role": "user", "content": message})

    if session["status"] == "awaiting_confirmation":
        return await handle_confirmation_state(session)
    else:
        return await handle_data_collection_state(session, client_code)
    
async def get_basic_details(session_id: str)-> JSONResponse:
    """Read-only view of a chat session for UI (no model/tool calls)."""
    if session_id not in sessions:
        return JSONResponse(
            status_code=404,
            content={"error": "Invalid or expired session_id"},
        )

    session = sessions[session_id]
    collected_data = session.get("campaign_data", {})
    status = session.get("status", "in_progress")
    progress = calculate_progress(collected_data)

    
    if status == "awaiting_confirmation" or status == "completed":
        payload_collected = collected_data
    else:
        trackable_fields = get_trackable_fields(collected_data)
        payload_collected = trackable_fields if trackable_fields else None

    return JSONResponse(
        content={
            "status": status,
            "data": payload_collected,
            "progress": progress,
            "last_activity": session.get("last_activity").isoformat()
            if session.get("last_activity")
            else None,
        }
    )

async def end_session(session_id: str):
    """End and cleanup a chat session."""
    if session_id not in sessions:
        return JSONResponse(status_code=404, content={"error": "Invalid session_id"})

    del sessions[session_id]
    return {"message": f"Session {session_id} ended successfully."}
