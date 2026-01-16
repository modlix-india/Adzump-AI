from typing import Optional
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from models.business_model import BusinessMetadata

# ENUMS
class MatchType(str, Enum):
    EXACT = "exact"
    PHRASE = "phrase"

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


# KEYWORDS UPDATION SERVICE MODELS

class UpdateKeywordsStrategyRequest(BaseModel):
    """Request model for updating keywords strategy"""
    
    customer_id: str = Field(..., description="Google Ads customer ID")
    campaign_id: str = Field(..., description="Campaign ID to analyze")
    ad_group_id: Optional[str] = Field(None, description="Ad group ID to analyze")
    login_customer_id: str = Field(..., description="Login customer ID for authorization")
    data_object_id: str = Field(..., description="Business/data object ID for context extraction")
    duration: Optional[str] = Field(
        None, 
        description="Date range (e.g., 'LAST_30_DAYS', 'LAST_90_DAYS', or '01/01/2025,31/12/2025')"
    )
    include_negatives: bool = Field(False, description="Include negative keywords in analysis")
    include_metrics: bool = Field(True, description="Include metrics like impressions, clicks, conversions")
    
    location_ids: Optional[List[str]] = Field(
        default_factory=lambda: ["geoTargetConstants/2840"],
        description="Location IDs for keyword suggestions (default: India)"
    )
    language_id: int = Field(default=1000,description="Language ID for keyword suggestions (default: 1000 for English)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "customer_id": "1234567890",
                "campaign_id": "9876543210",
                "ad_group_id": "1234567890",
                "login_customer_id": "1234567890",
                "data_object_id": "obj_12345",
                "duration": "LAST_30_DAYS",
                "include_negatives": False,
                "include_metrics": True,
                "location_ids": ["geoTargetConstants/2840"],
                "language_id": 1000
            }
        }
    }


class Keyword(BaseModel):
    """Represents a Google Ads Keyword with optional performance metrics.""" 
    # Core fields
    keyword: str
    criterion_id: str
    match_type: MatchType
    ad_group_id: str 
    ad_group_name: str
    campaign_id: str
    campaign_name: str
    status: str
    
    # Optional fields
    is_negative: bool = False
    quality_score: Optional[int] = None
    
    # Metrics
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    cost: float = 0.0
    ctr: float = 0.0
    average_cpc: float = 0.0
    cpl: Optional[float] = None
    conv_rate: float = 0.0
    
    @property
    def cost_micros(self) -> int:
        """Convert cost to micros for Google Ads API compatibility"""
        return int(self.cost * 1_000_000)
    
    def has_metrics(self) -> bool:
        """Check if this keyword has performance metrics"""
        return self.impressions > 0 or self.clicks > 0 or self.conversions > 0
    
    @classmethod
    def from_google_row(cls, row: dict) -> "Keyword":
        """Parse Google Ads API response row into Keyword object."""
        campaign = row.get("campaign", {})
        ad_group = row.get("adGroup", {})
        criterion = row.get("adGroupCriterion", {})
        keyword_info = criterion.get("keyword", {})
        metrics = row.get("metrics", {})
        
        keyword_text = keyword_info.get("text", "").strip().lower()
        criterion_id = str(criterion.get("criterionId", ""))
        clicks = int(metrics.get("clicks", 0))
        conversions = float(metrics.get("conversions", 0))
        
        cost_per_conversion_micros = float(metrics.get("costPerConversion", 0))
        cpl = cost_per_conversion_micros / 1_000_000 if cost_per_conversion_micros > 0 else None
        conv_rate = (conversions / clicks * 100) if clicks > 0 else 0.0
        
        return cls(
            keyword=keyword_text,
            criterion_id=criterion_id,
            match_type=keyword_info.get("matchType", "PHRASE"),
            ad_group_id=str(ad_group.get("id", "")),
            ad_group_name=ad_group.get("name", ""),
            campaign_id=str(campaign.get("id", "")),
            campaign_name=campaign.get("name", ""),
            status=criterion.get("status", "UNKNOWN"),
            is_negative=criterion.get("negative", False),
            quality_score=criterion.get("qualityInfo", {}).get("qualityScore"),
            impressions=int(metrics.get("impressions", 0)),
            clicks=clicks,
            conversions=conversions,
            cost=float(metrics.get("costMicros", 0)) / 1_000_000,
            ctr=float(metrics.get("ctr", 0.0)),
            average_cpc=float(metrics.get("averageCpc", 0.0)) / 1_000_000,
            cpl=cpl,
            conv_rate=conv_rate,
        )


class UpdateKeywordsStrategyResponse(BaseModel):
    """Response model for updating keywords strategy"""
    status: str = Field(..., description="success, no_data, or error")
    campaign_id: str
    total_keywords: int
    good_keywords: List[Dict] = Field(default_factory=list)
    poor_keywords: List[Dict] = Field(default_factory=list)
    top_performers: List[Dict] = Field(default_factory=list)
    suggestions: List[Dict] = Field(default_factory=list)
    suggestions_count: int = 0
    message: Optional[str] = None
    
    @staticmethod
    def _format_keyword(kw: 'Keyword') -> Dict:
        """Format keyword for API response"""
        return {
            "keyword": kw.keyword,
            "criterion_id": kw.criterion_id,
            "match_type": kw.match_type,
            "ad_group_name": kw.ad_group_name,
            "impressions": kw.impressions,
            "clicks": kw.clicks,
            "ctr": round(kw.ctr, 2),
            "conversions": kw.conversions,
            "cost": round(kw.cost, 2),
            "cpl": round(kw.cpl, 2) if kw.cpl else None,
            "quality_score": kw.quality_score,
            "conv_rate": round(kw.conv_rate, 2)
        }
    
    @classmethod
    def create_success(
        cls,
        campaign_id: str,
        all_keywords: List['Keyword'],
        good_keywords: List['Keyword'],
        poor_keywords: List[Dict],
        top_performers: List['Keyword'],
        suggestions: List[Dict]
    ) -> 'UpdateKeywordsStrategyResponse':
        """Factory method for success response"""
        return cls(
            status="success",
            campaign_id=campaign_id,
            total_keywords=len(all_keywords),
            good_keywords=[cls._format_keyword(kw) for kw in good_keywords],
            poor_keywords=poor_keywords,
            top_performers=[cls._format_keyword(kw) for kw in top_performers],
            suggestions=suggestions,
            suggestions_count=len(suggestions)
        )
    
    @classmethod
    def create_no_keywords(cls, campaign_id: str, keywords: List) -> 'UpdateKeywordsStrategyResponse':
        """Factory method for no keywords response"""
        return cls(
            status="no_data",
            campaign_id=campaign_id,
            message="No keywords found in campaign",
            total_keywords=len(keywords),
            good_keywords=[],
            poor_keywords=[],
            suggestions=[]
        )
    
    @classmethod
    def create_no_good_keywords(
        cls,
        campaign_id: str,
        all_keywords: List,
        poor_keywords: List[Dict]
    ) -> 'UpdateKeywordsStrategyResponse':
        """Factory method for no good keywords response"""
        return cls(
            status="success",
            campaign_id=campaign_id,
            message="No good keywords found to base suggestions on",
            total_keywords=len(all_keywords),
            good_keywords=[],
            poor_keywords=poor_keywords,
            suggestions=[]
        )


class FetchKeywordsResponse(BaseModel):
    status: str = Field(..., description="success or no_data")
    keywords: List[Keyword] = Field(default_factory=list)
    keywords_by_ad_group: dict = Field(default_factory=dict, description="Keywords grouped by ad_group_id")
    total_keywords: int = Field(default=0)
    total_ad_groups: int = Field(default=0)
    date_range_used: str = Field(...)
    
    class Config:
        arbitrary_types_allowed = True
    
    def get_keywords_list(self) -> List[Keyword]:
        """Convenience method for services that just need the keywords list."""
        return self.keywords
    
    def get_keywords_with_metrics(self) -> List[Keyword]:
        """Get only keywords that have performance metrics"""
        return [kw for kw in self.keywords if kw.has_metrics()]
    
    def get_ad_group_names(self) -> List[str]:
        """Get list of unique ad group names"""
        return list(set(kw.ad_group_name for kw in self.keywords))