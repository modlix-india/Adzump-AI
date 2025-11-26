
import json
from pydantic import  ValidationError
import logging

from services.openai_client import chat_completion
from models.campaign_data_model import CampaignData
from utils.helpers import validate_domain_exists
from typing import List, Dict, Any, Tuple , Optional
from third_party.google.services.google_customers_accounts import (
    list_accessible_customers as fetch_login_customers_accounts,
    fetch_customer_accounts as fetch_customer_accounts,
)

logger = logging.getLogger(__name__)

# --- ADD THESE HELPERS (NEAR OTHER HELPERS) ---

def format_numbered_options(items: List[Dict[str, Any]], title: str, name_key="name", id_key="id") -> str:
    lines = [title]
    for index, item in enumerate(items, start=1):
        display_name = item.get(name_key) or "Unnamed"
        display_id = item.get(id_key) or ""
        lines.append(f"{index}. {display_name} ({display_id})")
    
    return "\n".join(lines)

def flatten_mcc_response(raw_response: Any) -> List[Dict[str, Any]]:
    """
     MCC response is nested (list of single-item lists).
    Input example:
      [[{'id':'1002572931','name':'Test','is_manager':True}], [{'id':'2664052337','name':'Pavan','is_manager':True}], ...]
    Output:
      [{'id':'1002572931','name':'Test'}, {'id':'2664052337','name':'Pavan'}, ...]
    """
    flattened_accounts: List[Dict[str, Any]] = []

    if isinstance(raw_response, list):
        for outer_list in raw_response:
            if isinstance(outer_list, list) and outer_list:
                account_data = outer_list[0]  # take the single dict inside

                flattened_accounts.append({
                    "id": str(account_data.get("id", "")).strip(),
                    "name": str(account_data.get("name", "")).strip(),
                })

    # Ensure all entries have an ID
    return [account for account in flattened_accounts if account.get("id")]


# unified tool schema: model-visible single entry to request account selection operations
HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA = {
    "name": "handle_account_selection",
    "description": "Server-side helper: re-list or change manager or customer accounts. "
                   "action='mcc' to list MCCs, 'customer' to list customers under the saved or provided MCC, "
                   "or 'both' to reset both and re-list MCCs.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["mcc", "customer", "both"],
                "description": "mcc = re-list manager accounts; customer = re-list customers under current MCC; both = alias for mcc"
            },
            "login_customer_id": {
                "type": "string",
                "description": "Optional. Manager account id to use when action is 'customer'. "
                               "If omitted, the currently saved loginCustomerId will be used."
            },
            "retry": {
                "type": "integer",
                "description": "Number of automatic retry attempts for empty MCC results (default 1).",
                "default": 1
            },
            "client_code": {
                "type": "string",
                "description": "Client code for Google Ads auth. This is injected by backend; ignore any user-provided value."
            }
        },
        "required": ["action"]
    }
}


async def execute_list_accessible_customers(session: dict, client_code: str) -> str:
    """
    Calls Google Ads service to get MCCs, stores in session, updates state, and returns a numbered list message.
    Gracefully refines API errors for the user.
    """
    try:
        raw = await fetch_login_customers_accounts(client_code)
        mccs = flatten_mcc_response(raw)
        if not mccs:
            msg = ("I couldn't find any Google Ads manager (MCC) accounts for this client code. "
                   "Please check your connection or try a different code.")
            session["mcc_options"] = []
            session["status"] = "in_progress"
            return msg

        session["mcc_options"] = mccs
        session["status"] = "selecting_mcc"

        formatted_options_text = format_numbered_options(
            mccs,
            "Here are your available Google Ads manager accounts:"
        )

        return f"{formatted_options_text}\n\nPlease select one by number or name."

    except Exception as e:
        logger.exception("Error in list_accessible_customers tool")
        return ("Hmm, I couldn’t fetch your manager accounts right now. "
                "Please check that your connected Google Ads account is valid, or try again in a moment.")

async def execute_fetch_customer_accounts(session: dict, login_customer_id: str, client_code: str) -> str:
    """
    Calls Google Ads service to get customers under an MCC, stores in session, updates state, and returns a numbered list.
    Gracefully refines API errors for the user.
    """
    try:
        customer_accounts = await fetch_customer_accounts(login_customer_id, client_code)
        
        if not customer_accounts:
            session["customer_options"] = []
            session["status"] = "selecting_mcc"  # let them pick another MCC
            return ("No customer accounts were found under this manager account. "
                    "Please select a different manager from the list above or try again later.")

        session["customer_options"] = customer_accounts
        session["status"] = "selecting_customer"

        formatted_options_text = format_numbered_options(
            customer_accounts,
            f"Here are the customer accounts under Manager account(MCC) {login_customer_id}:"
        )

        return f"{formatted_options_text}\n\nPlease select one by number or name."

    except Exception as e:
        logger.exception("Error in fetch_customer_accounts tool")
        # Keep them on MCC selection to allow retry/change
        session["status"] = "selecting_mcc"
        return ("Sorry, there was an issue fetching customer accounts. "
                "This may happen if the selected manager lacks permissions. "
                "Please try another manager account.")


async def execute_handle_account_selection(
    session: dict,
    action: str,
    client_code: str,
    login_customer_id: Optional[str] = None,
    retry: int = 1,
) -> str:
    """
    Central unified account selection helper.
    - action: "mcc" | "customer" | "both"
    - Returns an assistant-ready message (string), similar to other execute_* helpers.
    """
    # Defensive gate: ensure core validated business fields are present before listing accounts
    try:
        required_business_fields = ["businessName", "websiteURL", "budget", "durationDays"]

        campaign_data = session.get("campaign_data", {})

        missing_fields = [
            field_name
            for field_name in required_business_fields
            if field_name not in campaign_data
        ]

        if missing_fields:
            # Don't fetch accounts if core required_business_fields are missing or invalid.
            return (
                "Required campaign details missing or invalid: "
                f"{', '.join(missing_fields)}. Please provide/correct them before listing accounts."
            )
    except Exception:
        # If something unexpected occurs while checking, fail safe by blocking and asking user to re-provide details.
        logger.exception("Error checking core fields in execute_handle_account_selection")
        return "I couldn't verify campaign details right now. Please ensure your businessName, websiteURL, budget and durationDays are provided."
    
    action = (action or "").lower()
    if action not in ("mcc", "customer", "both"):
        return "I didn’t understand which account you want to change. Do you want to change the manager account or the customer account?"

    # Always use server-side client_code (ignore anything coming from the model)
    clientCode = client_code

    # Convenience: access campaign data dict
    campaign = session.setdefault("campaign_data", {})
    
    # --- Case 1: change MCC (or both) ---
    if action in ("mcc", "both"):
        # Clear both MCC and customer from campaign data
        campaign.pop("loginCustomerId", None)
        campaign.pop("customerId", None)
        session["customer_options"] = []
        # Let list-accessible helper drive status + mcc_options
        attempts = 0
        last_msg = ""
        while attempts <= max(0, int(retry)):
            attempts += 1
            last_msg = await execute_list_accessible_customers(session, clientCode)
            mcc_opts = session.get("mcc_options") or []
            if mcc_opts:
                return last_msg
            # if still empty and we have retries left, loop again
            if attempts <= int(retry):
                continue
            # final empty
            return "No manager accounts were found for your profile. Please reauthenticate or try again later."

        # Should not reach here
        return last_msg or "No manager accounts were found for your profile. Please reauthenticate or try again later."

    # --- Case 2: change customer under current MCC ---
    if action == "customer":
        # Determine which MCC to use: either explicit login_customer_id from args or the saved loginCustomerId
        loginCustomerId = login_customer_id or campaign.get("loginCustomerId")
        if not loginCustomerId:
            return "There is no confirmed manager account yet. Please select a manager account first, then you can change the customer."

        # Clear only the customer selection and cached customer options
        campaign.pop("customerId", None)
        session["customer_options"] = []
        # Let customer helper handle fetch + status updates
        msg = await execute_fetch_customer_accounts(session, loginCustomerId, clientCode)
        return msg

def model_to_openai_schema(model_class, name, description):
    """Convert Pydantic model to OpenAI function schema."""
    schema = model_class.model_json_schema()
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required
        }
    }

def get_user_friendly_error(error_message: str, field_name: str) -> str:
    """Convert technical validation errors to user-friendly messages."""
    if field_name == "websiteURL":
        return "I notice there might be an issue with the URL format. Could you provide your website URL like example.com or https://example.com?"
    elif field_name == "budget":
        return "Could you provide the budget as a number? For example: 5000 or 5k"
    elif field_name == "durationDays":
        return "How many days should the campaign run? For example: 7 or 14"
    else:
        return f"Could you please provide a valid {field_name}?"


async def validate_and_extract_fields(function_args: dict) -> Tuple[dict, dict, list]:
    """
    Validate fields and extract valid ones, even if some fail.
    Returns: (valid_data, failed_fields, user_messages)
    """
    valid_data = {}
    failed_fields = {}
    user_messages = []
    
    for field_name, field_value in function_args.items():
        if field_value is None:
            continue
            
        try:
            temp_data = {field_name: field_value}
            validated = CampaignData(**temp_data)
            validated_dict = validated.model_dump(exclude_unset=True, exclude_none=True)

            if field_name == "websiteURL" and validated_dict.get("websiteURL"):
                url = validated_dict["websiteURL"]
                is_valid, error_msg = await validate_domain_exists(url)
                if not is_valid:
                    user_messages.append(error_msg)
                    continue

            valid_data.update(validated_dict)
        except ValidationError as e:
            error_msg = str(e.errors()[0].get('msg', ''))
            failed_fields[field_name] = field_value
            user_msg = get_user_friendly_error(error_msg, field_name)
            user_messages.append(user_msg)
    
    return valid_data, failed_fields, user_messages


SAVE_CAMPAIGN_TOOL_SCHEMA = model_to_openai_schema(
    CampaignData,
    name="save_campaign_data",
    description="Save advertising campaign data for setup."
)

CONFIRM_CAMPAIGN_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "confirm_campaign_creation",
        "description": "Call this function to confirm and finalize the campaign creation after the user has agreed to the summarized details.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

async def process_tool_call(session: dict, tool_call, response_message) -> Tuple[str, bool]:
    """
    Process a tool call and return (ai_message, data_was_extracted).
    """
    try:
        function_args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        return "", False
    
    # Validate and extract fields
    valid_data, failed_fields, user_messages = await validate_and_extract_fields(
        function_args
    )
    
    data_was_extracted = False
    if valid_data:
        session["campaign_data"].update(valid_data)
        data_was_extracted = True
    
    # Build tool output for second AI call
    tool_output = {
        "success": True,
        "saved_data": valid_data,
        "failed_fields": failed_fields,
        "user_messages": user_messages,
    }
    
    # Prepare messages for second AI call
    messages = list(session["chat_history"])
    messages.append(response_message)
    messages.append({
        "role": "tool",
        "name": tool_call.function.name,
        "content": json.dumps(tool_output),
        "tool_call_id": tool_call.id,
    })
    
    # Second AI call to generate conversational response
    try:
        second_response = await chat_completion(messages, tools=[{"type": "function", "function": SAVE_CAMPAIGN_TOOL_SCHEMA}], tool_choice="none")
        ai_message = second_response.choices[0].message.content or ""
    except Exception:
        ai_message = ""
    
    # Fallback: use user messages if AI didn't respond
    if user_messages and not ai_message.strip():
        ai_message = " ".join(user_messages)
    
    return ai_message, failed_fields, 
