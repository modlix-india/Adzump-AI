# agents/meta/constants.py


# Ad set constants

# BUDGET
MIN_DAILY_BUDGET_INR = 100
MIN_LIFETIME_BUDGET_INR = 100
INR_TO_MINOR_UNIT = 100

# SCHEDULE
SCHEDULE_BUFFER_SECONDS = 60

BID_STRATEGIES_REQUIRING_BID_AMOUNT = {
    "LOWEST_COST_WITH_BID_CAP",
    "COST_CAP",
    "TARGET_COST",
}

# TARGETING
FIXED_CATEGORIES = ["interests", "behaviors", "demographics"]
NON_DEMOGRAPHIC_TYPES = {"interests", "behaviors"}

# GEO TARGETING
VALID_DISTANCE_UNITS = {"kilometer", "mile"}

MAX_RADIUS_KM = 80
MAX_RADIUS_MILES = 50
MIN_RADIUS_KM = 17
MIN_RADIUS_MILES = 10


# Meta asset feed count limits
MAX_PRIMARY_TEXTS = 5  # primary text
MAX_HEADLINES = 5  # headline
MAX_DESCRIPTIONS = 5  # description
MAX_IMAGES = 10
MAX_VIDEOS = 10

# Meta asset character limits
MAX_PRIMARY_TEXT_CHARS = 125
MAX_HEADLINE_CHARS = 40
MAX_DESCRIPTION_CHARS = 30


# URL TAGS VALIDATOR
VALID_UTM_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "utm_id",
    "utm_adset",
    "utm_ad",
    "utm_placement",
    "utm_campaign_id",
    "utm_adset_id",
    "utm_ad_id",
}

VALID_META_MACROS = {
    "{{site_source_name}}",
    "{{campaign.name}}",
    "{{campaign.id}}",
    "{{adset.name}}",
    "{{adset.id}}",
    "{{ad.name}}",
    "{{ad.id}}",
    "{{placement}}",
}

DEFAULT_URL_TAGS = (
    "utm_source={{site_source_name}}"
    "&utm_medium=paid_social"
    "&utm_campaign={{campaign.name}}"
    "&utm_adset={{adset.name}}"
    "&utm_ad={{ad.name}}"
    "&utm_placement={{placement}}"
    "&utm_campaign_id={{campaign.id}}"
    "&utm_adset_id={{adset.id}}"
    "&utm_ad_id={{ad.id}}"
)
