
import json
from pydantic import  ValidationError
from structlog import get_logger    #type: ignore

from services.openai_client import chat_completion
from models.campaign_data_model import CampaignData
from utils.helpers import validate_domain_exists
from typing import Tuple , Optional


logger = get_logger(__name__)

# --- ADD THESE HELPERS (NEAR OTHER HELPERS) ---

def safe_args(tool_arguments: Optional[str]) -> dict: 
    """
    Safely parse tool_call.function.arguments into a dictionary.
    Returns {} if JSON is missing or invalid.
    """
    try:
        return json.loads(tool_arguments or "{}")
    except json.JSONDecodeError:
        return {}

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
    
    return ai_message, data_was_extracted, 
