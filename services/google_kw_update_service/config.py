# Google Keyword Update Service Configuration

# Keyword Update Service
TOP_PERFORMER_PERCENTAGE = 0.2

# Keyword Performance Classifier
CTR_THRESHOLD = 2.0
QUALITY_SCORE_THRESHOLD = 4  # Stricter: Flag QS ≤ 4 as poor
CPL_MULTIPLIER = 1.5
MIN_CLICKS_FOR_CONVERSIONS = 15  # Balanced: Suitable for real estate sales cycle
CONVERSION_RATE_THRESHOLD = 1.0  # Minimum acceptable conversion rate (%)
CRITICAL_CLICK_THRESHOLD = 50
CRITICAL_COST_THRESHOLD = 2000.0  # Flag keywords with high spend and no conversions
DEFAULT_MAX_CPL = 2000.0
DEFAULT_MIN_CPL = 50.0

# Enhanced Seed Expansion Feature
ENABLE_ENHANCED_SEED_EXPANSION = True
LLM_SEED_COUNT = 10  # Number of LLM variations to generate
AUTOCOMPLETE_MAX_SUGGESTIONS = 5  # Max autocomplete results per seed

# Performance Scoring Weights
PERFORMANCE_WEIGHTS = {
    "efficiency": 0.40,
    "impressions": 0.30,
    "conversions": 0.30,
}

# Multi-Factor Keyword Scorer
SCORE_WEIGHTS = {
    "volume": 0.25,
    "competition": 0.20,
    "business_relevance": 0.25,
    "intent": 0.15,
    "semantic": 0.15,
}

VOLUME_SCORE_TIERS = [
    (0, 100, 20),
    (100, 500, 40),
    (500, 1000, 60),
    (1000, 5000, 80),
    (5000, float("inf"), 100),
]

BUSINESS_RELEVANCE_SCORES = {
    "high": 100,
    "medium": 60,
    "low": 20,
}

INTENT_TYPE_SCORES = {
    "transactional": 100,
    "commercial": 80,
    "navigational": 60,
    "informational": 40,
    "unknown": 20,
}

CROSS_BUSINESS_PENALTY_MULTIPLIER = 0.5
MINIMUM_ACCEPTABLE_SCORE = 40

# LLM Analyzer
OPENAI_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS = 6000

# Data Fetcher
DEFAULT_LANGUAGE_ID = 1000
DEFAULT_LOCATION_IDS = ["geoTargetConstants/2356"]  # India
