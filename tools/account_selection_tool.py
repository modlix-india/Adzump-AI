import logging
from typing import List, Dict, Any, Optional

from third_party.google.services.google_customers_accounts import (
    list_manager_customers as fetch_login_customers_accounts,
    fetch_customer_accounts as fetch_customer_accounts,
    flatten_mcc_response,
)

logger = logging.getLogger(__name__)


def get_formatted_accounts_string(items: List[Dict[str, Any]], title: str, name_key: str = "name", id_key: str = "id") -> str:
    
    lines = [title]
    for index, item in enumerate(items, start=1):
        display_name = item.get(name_key) or "Unnamed"
        display_id = item.get(id_key) or ""
        lines.append(f"{index}. {display_name} ({display_id})")
    return "\n".join(lines)



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
            },
            "login_customer_id": {
                "type": "string",
            },
            "retry": {
                "type": "integer",
                "description": "Number of automatic retry attempts for empty MCC results (default 1).",
                "default": 1,
            },
        },
        "required": ["action"],
    },
}


async def execute_list_accessible_customers(session: dict,client_code: str) -> Dict[str, Any]:
    try:
        raw = await fetch_login_customers_accounts(client_code)
        mccs = flatten_mcc_response(raw)

        if not mccs:
            session["mcc_options"] = []
            session["status"] = "in_progress"
            return {
                "text": (
                    "I couldn't find any Google Ads manager (MCC) accounts for this client code. "
                    "Please check your connection or try a different code."
                ),
                "options": None,
                "selection_type": None,
            }

        session["mcc_options"] = mccs

        # If exactly one MCC -> auto-select it and immediately fetch customers
        if len(mccs) == 1:
            mcc_account = mccs[0]
            login_customer_id = mcc_account.get("id")
            login_customer_name = mcc_account.get("name")

            campaign = session.setdefault("campaign_data", {})
            campaign["loginCustomerId"] = login_customer_id

            session["status"] = "selecting_customer"

            info_msg = (
                "I found only one manager account associated with your profile:\n"
                f"- {login_customer_name} ({login_customer_id})\n\n"
                "I'll select this account automatically and fetch the customer accounts under it."
            )

            customer_result = await execute_fetch_customer_accounts(session, login_customer_id, client_code)

            return {
                "text": f"{info_msg}\n\n{customer_result['text']}",
                "options": customer_result.get("options"),
                "selection_type": customer_result.get("selection_type"),
                "message": info_msg
            }

        session["status"] = "selecting_mcc"

        formatted_text = get_formatted_accounts_string(
            mccs,
            "Here are your available Google Ads manager accounts:",
        )

        return {
            "text": f"{formatted_text}\n\nPlease select one by number or name.",
            "options": mccs,
            "message": "Here are your available Google Ads manager accounts:",              
            "selection_type": "mcc",      
        }

    except Exception:
        logger.exception("Error in list_accessible_customers")
        return {
            "text": (
                "Hmm, I couldn’t fetch your manager accounts right now. "
                "Please check your connection or try again in a moment."
            ),
            "options": None,
            "selection_type": None,
        }



async def execute_fetch_customer_accounts(session: dict, login_customer_id: str, client_code: str) -> Dict[str, Any]:
    try:
        customer_accounts = await fetch_customer_accounts(login_customer_id, client_code)

        if not customer_accounts:
            session["customer_options"] = []
            session["status"] = "selecting_mcc"
            return {
                "text": (
                    "No customer accounts were found under this manager account. "
                    "Please select a different manager from the list above or try again later."
                ),
                "options": None,
                "selection_type": None,
            }

        session["customer_options"] = customer_accounts

        # Auto-select single customer (UNCHANGED)
        if len(customer_accounts) == 1:
            customer = customer_accounts[0]
            customer_id = customer.get("id")
            customer_name = customer.get("name")
            campaign = session.setdefault("campaign_data", {})
            campaign["customerId"] = customer.get("id")

            session["status"] = "in_progress"

            return {
                "text": (
                    "I found only one customer account under the selected manager:\n"
                    f"- {customer_name} ({customer_id})\n\n"
                    "I've selected this customer automatically and will proceed with the setup."
                ),
                "options": None,
                "selection_type": None,
            }

        session["status"] = "selecting_customer"

        formatted_options_text = get_formatted_accounts_string(
            customer_accounts,
            f"Here are the customer accounts under Manager account (MCC) {login_customer_id}:",
        )

        return {
            "text": f"{formatted_options_text}\n\nPlease select one by number or name.",
            "options": customer_accounts,
            "message": f"Here are the customer accounts under Manager account (MCC) {login_customer_id}:",           
            "selection_type": "customer", 
        }

    except Exception:
        logger.exception("Error fetching customer accounts")
        session["status"] = "selecting_mcc"
        return {
            "text": (
                "Sorry, there was an issue fetching customer accounts. "
                "This may happen if the selected manager lacks permissions. "
                "Please try another manager account."
            ),
            "options": None,
            "selection_type": None,
        }


async def execute_handle_account_selection(
    session: dict,
    action: str,
    client_code: str,
    login_customer_id: Optional[str] = None,
    retry: int = 1,
) -> Dict[str, Any]:
    """
    Central unified account selection helper.

    """

    required_business_fields = [
        "businessName",
        "websiteURL",
        "budget",
        "durationDays",
    ]

    campaign_data = session.get("campaign_data", {})
    missing_fields = [
            field_name
            for field_name in required_business_fields
            if field_name not in campaign_data
        ]

    if missing_fields:
        return {
            "text": (
                "Required campaign details missing or invalid: "
                f"{', '.join(missing_fields)}. Please provide them before listing accounts."
            ),
            "options": None,
            "selection_type": None,
        }

    action = (action or "").lower()

    if action in ("mcc", "both"):
        campaign_data.pop("loginCustomerId", None)
        campaign_data.pop("customerId", None)
        session["customer_options"] = []

        attempts = 0
        last_result = None

        while attempts <= max(0, int(retry)):
            attempts += 1
            last_result = await execute_list_accessible_customers(session,client_code)
            if last_result.get("options"):
                return last_result

        return last_result or {
            "text": "No manager accounts were found for your profile.",
            "options": None,
            "selection_type": None,
        }

    if action == "customer":
        login_customer_id = login_customer_id or campaign_data.get("loginCustomerId")
        if not login_customer_id:
            return {
                "text": (
                    "There is no confirmed manager account yet. "
                    "Please select a manager account first."
                ),
                "options": None,
                "selection_type": None,
            }

        campaign_data.pop("customerId", None)
        session["customer_options"] = []

        return await execute_fetch_customer_accounts(
            session,
            login_customer_id,
            client_code,
        )

    return {
        "text": "I didn’t understand which account you want to change.",
        "options": None,
        "selection_type": None,
    }
