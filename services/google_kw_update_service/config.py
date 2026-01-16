# Google Keyword Update Service Configuration

# Keyword Update Service
TOP_PERFORMER_PERCENTAGE = 0.2

# Keyword Performance Classifier
CTR_THRESHOLD = 2.0
QUALITY_SCORE_THRESHOLD = 3
CPL_MULTIPLIER = 1.5
MIN_CLICKS_FOR_CONVERSIONS = 20
DEFAULT_MAX_CPL = 2000.0
DEFAULT_MIN_CPL = 50.0

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
LLM_MAX_TOKENS = 4000

# Data Fetcher
DEFAULT_LANGUAGE_ID = 1000
DEFAULT_LOCATION_IDS = ["geoTargetConstants/2356"]  # India
