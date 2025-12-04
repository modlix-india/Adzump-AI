import logging
from typing import List, Dict, Any ,Optional

from third_party.google.services.google_customers_accounts import (
    list_manager_customers as fetch_login_customers_accounts,
    fetch_customer_accounts as fetch_customer_accounts,
    flatten_mcc_response
)

logger = logging.getLogger(__name__)

def get_formatted_accounts_string(items: List[Dict[str, Any]], title: str, name_key="name", id_key="id") -> str:
    lines = [title]
    for index, item in enumerate(items, start=1):
        display_name = item.get(name_key) or "Unnamed"
        display_id = item.get(id_key) or ""
        lines.append(f"{index}. {display_name} ({display_id})")
    
    return "\n".join(lines)


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
        # If exactly one MCC -> auto-select it and immediately fetch customers
        if len(mccs) == 1:
            mcc_account = mccs[0]
            login_customer_id = mcc_account.get("id")
            login_customer_name = mcc_account.get("name")

            # Persist selected MCC on campaign data
            campaign = session.setdefault("campaign_data", {})
            campaign["loginCustomerId"] = login_customer_id

            # Update status to reflect next step (fetching customers)
            session["status"] = "selecting_customer"

            info_msg = (
                f"I found only one manager account associated with your profile:\n"
                f"- {login_customer_name} ({login_customer_id})\n\n"
                "I'll select this account automatically and fetch the customer accounts under it."
            )

            # Fetch customers under this MCC and return combined message
            customers_msg = await execute_fetch_customer_accounts(session, login_customer_id, client_code) # type: ignore
            # Prepend info message so user knows why we immediately listed customers
            return f"{info_msg}\n\n{customers_msg}"
        session["status"] = "selecting_mcc"

        formatted_options_text = get_formatted_accounts_string(
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
        # Auto-select single customer
        if len(customer_accounts) == 1:
            customer_accs = customer_accounts[0]
            customer_id = customer_accs.get("id")
            customer_name = customer_accs.get("name")

            # Persist selected customer on campaign data
            campaign = session.setdefault("campaign_data", {})
            campaign["customerId"] = customer_id

            #status as in_progress so handler can decide next step (summary or more collection)
            session["status"] = "in_progress"

            info_msg = (
                f"I found only one customer account under the manager (MCC) {login_customer_id}:\n"
                f"- {customer_name} ({customer_id})\n\n"
                "I've selected this customer automatically and will proceed with the setup."
            )

            return info_msg
        session["status"] = "selecting_customer"

        formatted_options_text = get_formatted_accounts_string(
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