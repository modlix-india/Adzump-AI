import json, uuid, re
from datetime import datetime, timezone, timedelta
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator, ValidationError
from typing import Optional, Tuple, Dict, Any
from openai_function_call import OpenAISchema
from word2number import w2n
from urllib.parse import urlparse
import dns.resolver

from services.openai_client import chat_completion
from services.session_manager import sessions, SESSION_TIMEOUT
from utils.prompt_loader import load_prompt


TODAY = datetime.now().strftime("%Y-%m-%d")

# PYDANTIC MODEL
class CampaignData(OpenAISchema):
    """Represents the data for an advertising campaign."""
    
    businessName: Optional[str] = Field(None, description="Name of the business/company")
    websiteURL: Optional[str] = Field(None, description="Website URL (must include http:// or https://)")
    budget: Optional[str] = Field(None, description="Advertising budget (numeric value)")
    durationDays: Optional[int] = Field(None, description="Campaign duration in days (numeric value)")
    loginCustomerId: Optional[str] = Field(None, description="The user's Google Ads customer ID.")


    @field_validator('websiteURL')
    def validate_website_url(cls, v):
        if v is None:
            return v
        
        v = v.strip()
        if not v.startswith('http'):
            v = f'https://{v}'
        
        try:
            parsed = urlparse(v)
            
            # Check required components
            if not parsed.scheme or not parsed.netloc:
                raise ValueError('Invalid website URL format')
            
            # Check scheme is http or https
            if parsed.scheme not in ['http', 'https']:
                raise ValueError('URL must use http or https protocol')
            
            # Validate hostname format
            hostname = parsed.hostname
            if not hostname:
                raise ValueError('Invalid website URL format')
            
            # Check for invalid characters in hostname
            if not re.match(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$', 
                        hostname, re.IGNORECASE):
                raise ValueError('Invalid website URL format')
            
            # Check TLD exists (at least one dot in hostname)
            if '.' not in hostname:
                raise ValueError('Invalid website URL format')
            
            return v
            
        except Exception:
            raise ValueError('Invalid website URL format')

    @field_validator('budget')
    def validate_budget(cls, v):
        if v is None:
            return v
        
        original_v = str(v).strip()
        v = original_v.lower()
        
        v = re.sub(r'\b(dollars?|rupees?|inr|usd|rs\.?|approximately|around|about|bucks)\b', '', v, flags=re.IGNORECASE)
        v = re.sub(r'[$,₹€£¥]', '', v)
        
        try:
            number_words = ['hundred', 'thousand', 'million', 'billion', 
                            'zero', 'one', 'two', 'three', 'four', 'five', 
                            'six', 'seven', 'eight', 'nine', 'ten',
                            'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
                            'sixteen', 'seventeen', 'eighteen', 'nineteen', 
                            'twenty', 'thirty', 'forty', 'fifty', 'sixty',
                            'seventy', 'eighty', 'ninety']
            
            if any(word in v for word in number_words):
                word_part = re.sub(r'\d+.*', '', v).strip()
                if word_part:
                    try:
                        return str(w2n.word_to_num(word_part))
                    except ValueError:
                        pass
        except Exception:
            pass
        
        lakh_crore_pattern = r'(\d+(?:\.\d+)?)\s*(lakh?s?|crore?s?)\b'
        lakh_crore_match = re.search(lakh_crore_pattern, v)
        if lakh_crore_match:
            number = float(lakh_crore_match.group(1))
            unit = lakh_crore_match.group(2).lower()
            if 'lakh' in unit:
                return str(int(number * 100000))
            elif 'crore' in unit:
                return str(int(number * 10000000))
        
        multiplier_pattern = r'(\d+(?:\.\d+)?)\s*([km])\b'
        multiplier_match = re.search(multiplier_pattern, v, flags=re.IGNORECASE)
        if multiplier_match:
            number = float(multiplier_match.group(1))
            multiplier = multiplier_match.group(2).lower()
            if multiplier == 'k':
                return str(int(number * 1000))
            elif multiplier == 'm':
                return str(int(number * 1000000))
        
        v = v.replace(',', '').replace(' ', '').strip()
        number_match = re.search(r'\d+(?:\.\d+)?', v)
        if number_match:
            try:
                return str(int(float(number_match.group())))
            except ValueError:
                pass
        
        raise ValueError(f'Could not parse budget: "{original_v}". Please provide a numeric value.')

    @field_validator('durationDays')
    def validate_duration(cls, v):
        if v is None:
            return v
        try:
            days = int(v)
            if days <= 0:
                raise ValueError('Duration must be a positive number')
            if days > 365:
                raise ValueError('Duration cannot exceed 365 days')
            return days
        except (ValueError, TypeError):
            raise ValueError('Duration must be a valid number of days')

    @field_validator('loginCustomerId')
    def validate_login_customer_id(cls, v):
        if v is None:
            return v
        clean_id = v.replace("-", "").replace(" ", "")
        if not clean_id.isdigit() or len(clean_id) != 10:
            raise ValueError('Customer ID must be a 10-digit number')
        return clean_id


# HELPER FUNCTIONS - SCHEMA & PROGRESS
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


def calculate_dates(duration_days):
    """Calculate start and end dates based on duration."""
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=duration_days)
    return {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d")
    }


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


# HELPER FUNCTIONS - VALIDATION
def get_user_friendly_error(error_message: str, field_name: str) -> str:
    """Convert technical validation errors to user-friendly messages."""
    if field_name == "websiteURL":
        return "I notice there might be an issue with the URL format. Could you provide your website URL like example.com or https://example.com?"
    elif field_name == "budget":
        return "Could you provide the budget as a number? For example: 5000 or 5k"
    elif field_name == "durationDays":
        return "How many days should the campaign run? For example: 7 or 14"
    elif field_name == "loginCustomerId":
        return "Could you provide a valid customer ID? It should be a 10-digit number."
    else:
        return f"Could you please provide a valid {field_name}?"

async def validate_domain_exists(url:str)-> Tuple[bool,str]:
    """
    validate if domain exists.
    Returns: (is_valid,error_message)
    """
    try:
        domain =  urlparse(url).hostname or url
        domain = re.sub(r'^https?://(www\.)?', '', domain, flags=re.IGNORECASE)
        domain = domain.split('/')[0]
        domain = domain.encode('idna').decode('ascii')

        resolver = dns.resolver.Resolver()
        resolver.timeout = 3
        resolver.lifetime = 3
        try:
            resolver.resolve(domain, "A")
            return True, ""
        except (dns.resolver.NoAnswer,dns.resolver.NXDOMAIN):
            resolver.resolve(domain, "AAAA")
            return True, ""
    except dns.resolver.NXDOMAIN:
        return False, f"The domain '{domain}' does not exist. Please check the URL."
    except dns.resolver.NoAnswer:
        return False, f"This domain '{domain}' has no DNS records.Please verify the URL."
    except dns.resolver.Timeout:
        return True, ""
    except Exception:
        return False, f"Invalid domain '{domain}'. Please check the URL."

async def validate_and_extract_fields(function_args: dict, session_data: dict) -> Tuple[dict, dict, list]:
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


# TOOL SCHEMAS
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
                dates = calculate_dates(int(session["campaign_data"]["durationDays"]))
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
                        function_args, session["campaign_data"]
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
        function_args, session["campaign_data"]
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
    
    return ai_message, data_was_extracted


async def handle_data_collection_state(session: dict, login_customer_id: str = None) -> JSONResponse:
    """Handle in_progress (data collection) state logic."""
    
    # Handle login customer ID from header/param
    if login_customer_id and not session["campaign_data"].get("loginCustomerId"):
        valid_id_data, _, _ = await validate_and_extract_fields(
            {"loginCustomerId": login_customer_id}, session["campaign_data"]
        )

        if valid_id_data.get("loginCustomerId"):
            session["campaign_data"].update(valid_id_data)
        else:
            return JSONResponse(
                content={"status": "error", "message": "Invalid customer ID. Please provide a 10-digit customer ID."},
                status_code=400
            )

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