import re
from typing import Optional
from pydantic import Field, field_validator
from instructor import OpenAISchema
from word2number import w2n
from urllib.parse import urlparse

class CampaignData(OpenAISchema):
    """Represents the data for an advertising campaign."""
    
    businessName: Optional[str] = Field(None, description="Name of the business/company")
    websiteURL: Optional[str] = Field(None, description="Website URL (must include http:// or https://)")
    budget: Optional[str] = Field(None, description="Advertising budget (numeric value)")
    durationDays: Optional[int] = Field(None, description="Campaign duration in days (numeric value)")
    loginCustomerId: Optional[str] = Field(None, description="The user's Google Ads customer ID.")
    customerId: Optional[str] = None 

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