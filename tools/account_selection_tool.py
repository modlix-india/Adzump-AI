from structlog import get_logger    #type: ignore
from typing import List, Dict, Any, Optional
from models.campaign_data_model import CampaignData

from third_party.google.services.google_customers_accounts import (
    list_manager_customers as fetch_login_customers_accounts,
    fetch_customer_accounts as fetch_customer_accounts,
    flatten_mcc_response,
)

def all_required_campaign_fields_collected(campaign_data: dict) -> bool:
    required_fields = CampaignData.model_fields.keys()
    return all(field in campaign_data for field in required_fields)


logger = get_logger(__name__)

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
                "message": (
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
                "message": info_msg,
                "options": customer_result.get("options"),
                "selection_type": customer_result.get("selection_type"),
            }

        session["status"] = "selecting_mcc"

        return {
            "message": "Here are your available Google Ads manager accounts:",
            "options": mccs,
            "selection_type": "mcc",
        }

    except Exception:
        logger.exception("Error in list_accessible_customers")
        return {
            "message": (
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
                "message": (
                    "No customer accounts were found under this manager account. "
                    "Please select a different manager from the list above or try again later."
                ),
                "options": None,
                "selection_type": None,
            }

        session["customer_options"] = customer_accounts

        if len(customer_accounts) == 1:
            customer = customer_accounts[0]
            customer_id = customer.get("id")
            customer_name = customer.get("name")
            campaign = session.setdefault("campaign_data", {})
            campaign["customerId"] = customer.get("id")

            session["status"] = "in_progress"

            return {
                "message": (
                    "I found only one customer account under the selected manager:\n"
                    f"- {customer_name} ({customer_id})\n\n"
                    "I've selected this customer automatically and will proceed with the setup."
                ),
                "options": None,
                "selection_type": None,
            }

        session["status"] = "selecting_customer"

        return {
            "message": (
                f"Here are the customer accounts under Manager account (MCC) {login_customer_id}:"
            ),
            "options": customer_accounts,
            "selection_type": "customer",
        }

    except Exception:
        logger.exception("Error fetching customer accounts")
        session["status"] = "selecting_mcc"
        return {
            "message": (
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
            "message": (
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
            "message": "No manager accounts were found for your profile.",
            "options": None,
            "selection_type": None,
        }

    if action == "customer":
        login_customer_id = login_customer_id or campaign_data.get("loginCustomerId")
        if not login_customer_id:
            return {
                "message": (
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
        "message": "I didn’t understand which account you want to change.",
        "options": None,
        "selection_type": None,
    }
async def handle_account_selection_by_status(
    session: dict,
    message: str,
    client_code: str,
) -> dict:


    selected_id = message.strip()

    if session["status"] == "selecting_mcc":
        mcc_options = session.get("mcc_options", [])
        valid_mcc_ids = {str(mcc["id"]) for mcc in mcc_options}

        if selected_id not in valid_mcc_ids:
            return {
                "next_status": "selecting_mcc",
                "message": "Invalid selection. Please choose a manager account from the list below.",
                "selection": {
                    "type": "mcc",
                    "options": mcc_options,
                },
            }

        session["campaign_data"]["loginCustomerId"] = selected_id

        result = await execute_fetch_customer_accounts(
            session=session,
            login_customer_id=selected_id,
            client_code=client_code,
        )

        selection = None
        if result.get("options"):
            selection = {
                "type": result.get("selection_type"),
                "options": result.get("options"),
            }

        return {
            "next_status": session["status"],  # set by execute_fetch_customer_accounts
            "message": result.get("message"),
            "selection": selection,
        }

    if session["status"] == "selecting_customer":
        customer_options = session.get("customer_options", [])
        valid_customer_ids = {str(c["id"]) for c in customer_options}

        if selected_id not in valid_customer_ids:
            return {
                "next_status": "selecting_customer",
                "message": "Invalid selection. Please choose a customer account from the list below.",
                "selection": {
                    "type": "customer",
                    "options": customer_options,
                },
            }

        session["campaign_data"]["customerId"] = selected_id

        if all_required_campaign_fields_collected(session["campaign_data"]):
            return {
                "next_status": "awaiting_confirmation",
                "message": "",  # chat_service will build summary
                "requires_summary": True,
            }

        return {
            "next_status": session["status"],
            "message": "Customer account selected successfully.",
        }

    return {
        "next_status": session["status"],
        "message": "Account selection is not expected in the current state.",
        "error": True,
    }
