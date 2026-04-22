# BUDGET
# SOURCE_LINK = "https://developers.facebook.com/docs/marketing-api/reference/ad-campaign"
MIN_DAILY_BUDGET_INR = 100
MIN_LIFETIME_BUDGET_INR = 100
INR_TO_MINOR_UNIT = 100

# SCHEDULE
SCHEDULE_BUFFER_SECONDS = 60  # Minimum buffer required by Meta API for start_time

# TARGETING
# SOURCE_LINK = "https://developers.facebook.com/docs/marketing-api/audiences/reference/targeting-search/"
FIXED_CATEGORIES = ["interests", "behaviors", "demographics"]
NON_DEMOGRAPHIC_TYPES = {"interests", "behaviors"}

# Meta Geo Targeting limits (City radius)
# SOURCE_LINK = "https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting/"
MAX_RADIUS_KM = 80
MAX_RADIUS_MILES = 50
MIN_RADIUS_KM = 17
MIN_RADIUS_MILES = 10
VALID_DISTANCE_UNITS = {"kilometer", "mile"}
MIN_AGE = 18
MAX_AGE = 65
GENDER_MALE_VALUE = 1
GENDER_FEMALE_VALUE = 2
DEFAULT_DISTANCE_UNIT = "kilometer"


# Meta asset feed spec count limits
# SOURCE_LINK = "https://www.facebook.com/business/help/344106239654869?id=244556379685063"
MAX_PRIMARY_TEXTS = 5  # primary text
MAX_HEADLINES = 5  # headline
MAX_DESCRIPTIONS = 5  # description
MAX_IMAGES = 10
MAX_VIDEOS = 10

# Meta asset character limits (Hard API Limits)
# The API accepts these larger sizes, but truncates them in UI displays.
# SOURCE_LINK = "https://www.facebook.com/business/ads-guide/update/image/audience-network-native"
MAX_PRIMARY_TEXT_CHARS = 2200
MAX_HEADLINE_CHARS = 255
MAX_DESCRIPTION_CHARS = 255

# Meta asset character limits (Recommended Display Limits — enforced via AI prompt, not Pydantic)
# These are the safe limits before text gets cut off by "See More" on mobile feeds.
# SOURCE_LINK = "https://www.facebook.com/business/help/223409425500940?id=271710926837064"
RECOMMENDED_PRIMARY_TEXT_CHARS = 125
RECOMMENDED_HEADLINE_CHARS = 40
RECOMMENDED_DESCRIPTION_CHARS = 30


# URL TAGS VALIDATOR
# SOURCE_LINK = "https://www.facebook.com/business/help/2360940870872492"
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
