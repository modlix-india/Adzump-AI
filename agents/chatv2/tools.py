"""Tool Schemas - OpenAI function calling definitions."""

from core.chatv2.fields import build_tool_schema

UPDATE_AD_PLAN_TOOL_NAME = "update_ad_plan"
CONFIRM_CAMPAIGN_TOOL_NAME = "confirm_campaign_creation"
HANDLE_ACCOUNT_SELECTION_TOOL_NAME = "handle_account_selection"

UPDATE_AD_PLAN_TOOL_SCHEMA = build_tool_schema(
    name=UPDATE_AD_PLAN_TOOL_NAME,
    description=(
        "Update ad plan with campaign data. "
        "Extract and save business name, website URL, budget, and duration from the user's message."
    ),
)

CONFIRM_CAMPAIGN_TOOL_SCHEMA = {
    "name": CONFIRM_CAMPAIGN_TOOL_NAME,
    "description": (
        "Call this function to confirm and finalize the campaign creation "
        "after the user has agreed to the summarized details."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA = {
    "name": HANDLE_ACCOUNT_SELECTION_TOOL_NAME,
    "description": (
        "Server-side helper: re-list or change accounts. "
        "action='parent_account', 'account', or 'both'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["parent_account", "account", "both"]},
            "retry": {"type": "integer", "description": "Retry attempts", "default": 1},
        },
        "required": ["action"],
    },
}


def _wrap(schema: dict) -> dict:
    return {"type": "function", "function": schema}


def get_collection_tools() -> list[dict]:
    return [_wrap(UPDATE_AD_PLAN_TOOL_SCHEMA), _wrap(HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA)]


def get_confirmation_tools() -> list[dict]:
    return [
        _wrap(CONFIRM_CAMPAIGN_TOOL_SCHEMA),
        _wrap(UPDATE_AD_PLAN_TOOL_SCHEMA),
        _wrap(HANDLE_ACCOUNT_SELECTION_TOOL_SCHEMA),
    ]
