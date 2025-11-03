"""
Pydantic models for Google Keyword Service
Provides type safety and validation for keyword research operations
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from models.business_model import BusinessMetadata
from enum import Enum

# ENUMS
class MatchType(str, Enum):
    EXACT = "exact"
    PHRASE = "phrase"
    BROAD = "broad"

class CompetitionLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"

class KeywordType(str, Enum):
    BRAND = "brand"
    GENERIC = "generic"

# KEYWORD SUGGESTION MODELS
class KeywordSuggestion(BaseModel):
    keyword: str = Field(..., min_length=2, max_length=80, description="Keyword text")
    volume: int = Field(ge=0, description="Average monthly search volume")
    competition: CompetitionLevel = Field(default=CompetitionLevel.UNKNOWN, description="Competition level")
    competitionIndex: float = Field(ge=0.0, le=1.0, default=0.0, description="Competition index (0-1)")
    
    @field_validator('keyword')
    @classmethod
    def normalize_keyword(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Keyword must be a string")
        return v.strip().lower()
    
    @property
    def roi_score(self) -> float:
        return self.volume / (1 + self.competitionIndex) if self.competitionIndex > 0 else self.volume
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "keyword": "plumber near me",
                "volume": 5400,
                "competition": "MEDIUM", 
                "competitionIndex": 0.52
            }
        }
    }

class OptimizedKeyword(KeywordSuggestion):
    match_type: MatchType = Field(default=MatchType.PHRASE, description="Keyword match type")
    rationale: str = Field(default="AI selected", description="Selection rationale")
    is_cross_business: bool = Field(default=False, description="Flag for cross-business terms")
    # phase: Optional[str] = Field(default=None, description="Selection phase")  # Remove if not needed
    
    @model_validator(mode='after')
    def validate_cross_business_match_type(self) -> 'OptimizedKeyword':
        if self.is_cross_business and self.match_type != MatchType.PHRASE:
            object.__setattr__(self,"match_type", MatchType.PHRASE)
            object.__setattr__(self,"rationale", f"{self.rationale} [Corrected to phrase: cross-business term]")
        return self
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "keyword": "emergency plumber bangalore",
                "volume": 1200,
                "competition": "MEDIUM",
                "competitionIndex": 0.48,
                "match_type": "phrase", 
                "rationale": "High-intent location-based search",
                "is_cross_business": False
            }
        }
    }

class NegativeKeyword(BaseModel):
    keyword: str = Field(..., min_length=2, max_length=80, description="Negative keyword text")
    reason: str = Field(default="Budget protection", description="Reason for exclusion")
    
    @field_validator('keyword')
    @classmethod
    def normalize_keyword(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Keyword must be a string")
        return v.strip().lower()
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "keyword": "diy plumbing",
                "reason": "Users looking for DIY solutions, not hiring services"
            }
        }
    }

# LLM RESPONSE MODELS
class KeywordSelectionResponse(BaseModel):
    keywords: List[Dict[str, Any]] = Field(default_factory=list, description="Selected keywords")
    
    @field_validator('keywords')
    @classmethod
    def validate_keywords(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        validated = []
        for kw in v:
            if isinstance(kw, dict) and 'keyword' in kw:
                kw.setdefault('match_type', 'phrase')
                kw.setdefault('is_cross_business', False)
                kw.setdefault('rationale', 'AI selected')
                validated.append(kw)
        return validated
    
class GoogleNegativeKwReq(BaseModel):
    data_object_id: str = Field(..., description="Data object ID for business context")
    positive_keywords: List[OptimizedKeyword] = Field(..., description="List of positive keywords to analyze")

class NegativeKeywordResponse(BaseModel):
    negative_keywords: List[Dict[str, str]] = Field(default_factory=list, description="Negative keywords")
    
    @field_validator('negative_keywords')
    @classmethod
    def validate_negatives(cls, v: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        validated = []
        for kw in v:
            if isinstance(kw, dict) and 'keyword' in kw:
                kw.setdefault('reason', 'Budget protection')
                validated.append(kw)
        return validated

# SERVICE REQUEST/RESPONSE MODELS  
class KeywordResearchRequest(BaseModel):
    customer_id: str = Field(..., description="Google Ads customer ID")
    data_object_id:str = Field(..., description="Data object ID")
    keyword_type: KeywordType = Field(default=KeywordType.GENERIC, description="Type of keywords to generate")
    location_ids: List[str] = Field(default_factory=lambda: ["geoTargetConstants/2840"], description="Target location IDs")
    language_id: int = Field(default=1000, description="Target language ID")
    seed_count: int = Field(default=40, ge=10, le=100, description="Number of seed keywords")
    target_positive_count: int = Field(default=30, ge=10, le=100, description="Target positive keywords count")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "customer_id": "1234567890",
                "data_object_id": "abc123xyz", 
                "keyword_type": "brand",
                "location_ids": ["geoTargetConstants/2356"],
                "language_id": 1000,
                "seed_count": 40,
                "target_positive_count": 30
            }
        }
    }

class KeywordResearchResult(BaseModel):
    positive_keywords: List[OptimizedKeyword] = Field(default_factory=list, description="Optimized positive keywords")
    brand_info: BusinessMetadata = Field(default_factory=BusinessMetadata, description="Business metadata")
    unique_features: List[str] = Field(default_factory=list, description="Business unique features")
    
    @property
    def total_keywords(self) -> int:
        return len(self.positive_keywords)
    
    @property
    def match_type_distribution(self) -> Dict[str, int]:
        distribution = {"exact": 0, "phrase": 0, "broad": 0}
        for kw in self.positive_keywords:
            distribution[kw.match_type.value] += 1
        return distribution
    
    @property
    def cross_business_count(self) -> int:
        return sum(1 for kw in self.positive_keywords if kw.is_cross_business)
    
    def get_match_type_percentage(self) -> Dict[str, float]:
        if not self.positive_keywords:
            return {"exact": 0.0, "phrase": 0.0, "broad": 0.0}
        
        total = len(self.positive_keywords)
        dist = self.match_type_distribution
        return {
            match_type: round((count / total) * 100, 1)
            for match_type, count in dist.items()
        }
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "positive_keywords": [
                    {
                        "keyword": "acme plumbing bangalore",
                        "volume": 890,
                        "competition": "LOW", 
                        "competitionIndex": 0.32,
                        "match_type": "phrase",
                        "rationale": "Brand + location high-intent search",
                        "is_cross_business": False
                    }
                ],
                "brand_info": {
                    "brand_name": "Acme Plumbing",
                    "business_type": "Plumbing Services", 
                    "primary_location": "Bangalore",
                    "service_areas": ["Koramangala", "Indiranagar"],
                    "brand_keywords": ["acme plumbing"]
                },
                "unique_features": ["24/7 emergency service", "licensed plumbers"]
            }
        }
    }