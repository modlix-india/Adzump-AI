from datetime import datetime
from typing import Optional, Union

def normalize_time(time_input: Optional[Union[str, datetime]]) -> Optional[str]:
    """
    Normalizes time input to ISO 8601 string format required by Meta Ads API.
    """
    if not time_input:
        return None
    
    if isinstance(time_input, datetime):
        return time_input.isoformat()
    
    if isinstance(time_input, str):
        # Allow pass-through if already string, assuming valid ISO
        return time_input
        
    return str(time_input)
