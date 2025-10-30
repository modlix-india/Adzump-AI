from typing import List, Any
from pydantic import BaseModel, Field, field_validator

# BUSINESS METADATA MODELS
class BusinessMetadata(BaseModel):
    brand_name: str = Field(default="Unknown", description="Business brand name")
    business_type: str = Field(default="Unknown", description="Type of business")
    primary_location: str = Field(default="Unknown", description="Primary business location")
    service_areas: List[str] = Field(default_factory=list, description="Service area locations")
    unique_features: List[str] = Field(default_factory=list, description="Unique business features")
    
    @field_validator('brand_name', 'business_type', 'primary_location')
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Must be a string")
        return v if v.strip() else "Unknown"
    
    @field_validator('service_areas','unique_features')
    @classmethod
    def validate_string_lists(cls, v: List[Any]) -> List[str]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        return [item.strip() for item in v if isinstance(item, str) and item.strip()]
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "brand_name": "Acme Plumbing",
                "business_type": "Plumbing Services",
                "primary_location": "Bangalore",
                "service_areas": ["Koramangala", "Indiranagar", "Whitefield"],
                "unique_features": ["24/7 emergency service", "licensed plumbers"]
            }
        }
    }

