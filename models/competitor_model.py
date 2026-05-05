from __future__ import annotations
from pydantic import BaseModel, Field


class RelatedQuery(BaseModel):
    query: str
    value: float | str


class KeywordAlternatives(BaseModel):
    top: list[RelatedQuery] = Field(default_factory=list)
    rising: list[RelatedQuery] = Field(default_factory=list)


class TrendInterestMetrics(BaseModel):
    values: list[int] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    avg_interest: float = 0.0
    max_interest: int = 0
    min_interest: int = 0
    current_interest: int = 0
    trend_direction: str = "stable"
    trend_slope: float = 0.0


class TrendInterestResponse(BaseModel):
    success: bool = True
    keywords: list[str] = Field(default_factory=list)
    timeframe: str = "today 12-m"
    data: dict[str, TrendInterestMetrics] = Field(default_factory=dict)


class RelatedQueriesResponse(BaseModel):
    success: bool = True
    keyword: str
    top: list[RelatedQuery] = Field(default_factory=list)
    rising: list[RelatedQuery] = Field(default_factory=list)


class TrendingSearchResponse(BaseModel):
    success: bool = True
    country: str
    date: str
    trending_searches: list[str] = Field(default_factory=list)


class KeywordOpportunityScoring(BaseModel):
    """Pydantic model for strategic keyword scoring and LLM output."""

    keyword: str = Field(..., description="The keyword text")
    opportunity_score: float = Field(default=0, ge=0, le=100)
    recommended_action: str = ""
    reasoning: str = ""
    competitor_advantage: str | None = Field(
        None,
        description="Why this keyword gives the competitor a strategic edge",
    )


class CompetitorKeyword(KeywordOpportunityScoring):
    category: str = Field(
        default="general",
        description="Category: Feature-based, Audience-based, Use-case, Comparison, Brand-based, Long-tail",
    )
    source: str = Field(
        default="content",
        description="Where it was found: heading, title, meta, url_path, content, autocomplete",
    )
    intent: str = Field(
        default="commercial",
        description="Search intent: informational, commercial, transactional, navigational",
    )
    match_type: str = Field(
        default="PHRASE",
        description="LLM-suggested match type for Google Ads: EXACT, PHRASE",
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
    extracted_keywords: list[CompetitorKeyword] = Field(
        default_factory=list, description="Keywords extracted from competitor site"
    )
    features: list[str] = Field(
        default_factory=list, description="Core product features extracted"
    )
    summary: str | None = Field(
        None, description="Brief summary of competitor positioning"
    )
    reasoning: str | None = Field(
        None, description="AI reasoning for why this is a competitor"
    )


class CompetitorAnalysisResult(BaseModel):
    competitor_analysis: list[Competitor] = Field(default_factory=list)
    enriched_keywords: list[CompetitorKeyword] = Field(default_factory=list)

    @staticmethod
    def load_from_record(record: dict) -> tuple[list[Competitor], list[Competitor]]:
        """
        Utility to parse and validate competitor lists from a raw database(storage) record.
        Returns: (raw_competitors_to_analyze, existing_competitor_analysis)
        """
        raw_comps = [
            Competitor.model_validate(c)
            for c in record.get("competitors", [])
            if isinstance(c, dict)
        ]
        existing_comps = [
            Competitor.model_validate(c)
            for c in record.get("competitor_analysis", [])
            if isinstance(c, dict)
        ]
        return raw_comps, existing_comps
