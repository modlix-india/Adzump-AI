from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class RelatedQuery(BaseModel):
    query: str
    value: float | str


class KeywordAlternatives(BaseModel):
    top: List[RelatedQuery] = Field(default_factory=list)
    rising: List[RelatedQuery] = Field(default_factory=list)


class TrendInterestMetrics(BaseModel):
    values: List[int] = Field(default_factory=list)
    dates: List[str] = Field(default_factory=list)
    avg_interest: float = 0.0
    max_interest: int = 0
    min_interest: int = 0
    current_interest: int = 0
    trend_direction: str = "stable"
    trend_slope: float = 0.0


class TrendInterestResponse(BaseModel):
    success: bool = True
    keywords: List[str] = Field(default_factory=list)
    timeframe: str = "today 12-m"
    data: Dict[str, TrendInterestMetrics] = Field(default_factory=dict)


class RelatedQueriesResponse(BaseModel):
    success: bool = True
    keyword: str
    top: List[RelatedQuery] = Field(default_factory=list)
    rising: List[RelatedQuery] = Field(default_factory=list)


class TrendingSearchResponse(BaseModel):
    success: bool = True
    country: str
    date: str
    trending_searches: List[str] = Field(default_factory=list)


class KeywordOpportunityScoring(BaseModel):
    """Pydantic model for strategic keyword scoring and LLM output."""

    keyword: str = Field(..., description="The keyword text")
    opportunity_score: float = Field(default=0, ge=0, le=100)
    difficulty: str = "medium"
    strategic_fit: str = "moderate"
    recommended_action: str = ""
    reasoning: str = ""


class CompetitorKeyword(KeywordOpportunityScoring):
    category: str = Field(
        default="general",
        description="Category: Feature-based, Audience-based, Use-case, Comparison, Brand-based, Long-tail",
    )
    source: str = Field(
        default="content",
        description="Where it was found: heading, title, meta, url_path, content, autocomplete",
    )
    relevance: float = Field(
        default=0.5, description="Relevance score 0-1", ge=0.0, le=1.0
    )
    intent: str = Field(
        default="commercial",
        description="Search intent: informational, commercial, transactional, navigational",
    )
    suggested_match_type: str = Field(
        default="BROAD",
        description="LLM-suggested match type for Google Ads: EXACT, PHRASE, BROAD",
    )
    competitor_advantage: Optional[str] = Field(
        None,
        description="Why this keyword gives the competitor a strategic edge",
    )

    volume: int = 0
    competition: str = "UNKNOWN"
    competitionIndex: float = 0.0
    trend_direction: str = "stable"


class Competitor(BaseModel):
    name: str = Field(..., description="Name of the competitor")
    url: str = Field(..., description="Homepage URL of the competitor")
    is_validated: bool = Field(
        default=False,
        description="Whether the competitor has been validated via scraping",
    )
    pages_scraped: int = Field(
        default=1, description="Number of pages scraped for this competitor"
    )
    extracted_keywords: List[CompetitorKeyword] = Field(
        default_factory=list, description="Keywords extracted from competitor site"
    )
    features: List[str] = Field(
        default_factory=list, description="Core product features extracted"
    )
    summary: Optional[str] = Field(
        None, description="Brief summary of competitor positioning"
    )
    reasoning: Optional[str] = Field(
        None, description="AI reasoning for why this is a competitor"
    )


class CompetitorAnalysisResult(BaseModel):
    competitor_analysis: List[Competitor]
    enriched_keywords: List[CompetitorKeyword]
