# agents/meta/constants.py


#Campaign constants 

VALID_OBJECTIVES = {
    "OUTCOME_AWARENESS",
    "OUTCOME_TRAFFIC",
    "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS",
    "OUTCOME_SALES",
    "OUTCOME_APP_PROMOTION",
}

VALID_STATUSES = {
    "ACTIVE",
    "PAUSED",
}

VALID_SPECIAL_AD_CATEGORIES = {
    "NONE",
    "EMPLOYMENT",
    "HOUSING",
    "CREDIT",
    "ISSUES_ELECTIONS_POLITICS",
}

#Ad set constants 

#BUDGET 
MIN_DAILY_BUDGET_INR = 100
MIN_LIFETIME_BUDGET_INR = 100
INR_TO_MINOR_UNIT = 100
VALID_BUDGET_TYPES = {"DAILY", "LIFETIME"}

#SCHEDULE 
SCHEDULE_BUFFER_SECONDS = 60

#BIDDING 
BID_STRATEGIES_REQUIRING_BID_AMOUNT = {
    "LOWEST_COST_WITH_BID_CAP",
    "COST_CAP",
    "TARGET_COST"
}

#PROMOTED OBJECT 
VALID_PIXEL_EVENTS = {
    "LEAD", "PURCHASE", "ADD_TO_CART", "INITIATED_CHECKOUT",
    "ADD_PAYMENT_INFO", "COMPLETE_REGISTRATION", "SEARCH",
    "VIEW_CONTENT", "SUBSCRIBE", "CONTACT"
}

VALID_STORE_PATTERNS = [
    "apps.apple.com",
    "play.google.com",
    "itunes.apple.com"
]

#TARGETING 
FIXED_CATEGORIES = ["interests", "behaviors", "demographics"]
NON_DEMOGRAPHIC_TYPES = {"interests", "behaviors"}

#GEO TARGETING
VALID_DISTANCE_UNITS = {"kilometer", "mile"}

MAX_RADIUS_KM = 80
MAX_RADIUS_MILES = 50
MIN_RADIUS_KM = 17
MIN_RADIUS_MILES = 10

# billing_event — what you pay for
VALID_BILLING_EVENTS = {
    "IMPRESSIONS",      # pay per 1000 impressions
    "LINK_CLICKS",      # pay per link click
    "PAGE_LIKES",       # pay per page like
    "POST_ENGAGEMENT",  # pay per post engagement
    "VIDEO_VIEWS",      # pay per video view
    "APP_INSTALLS",     # pay per app install
    "OFFER_CLAIMS",     # pay per offer claim
}


# Valid promoted_object type per optimization_goal
# If mismatch → Meta rejects with cryptic error
OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP = {
    "OFFSITE_CONVERSIONS": "PIXEL",
    "LEAD_GENERATION": "PAGE",
    "APP_INSTALLS": "APP",
    "REACH": None,
    "BRAND_AWARENESS": None,
    "LINK_CLICKS": None,
    "LANDING_PAGE_VIEWS": None,
    "POST_ENGAGEMENT": None,
    "VIDEO_VIEWS": None,
    "THRUPLAY": None,
}


#Ad creative constants 

VALID_CREATIVE_TYPES = {"IMAGE", "VIDEO", "CAROUSEL"}

# Meta asset feed count limits
MAX_BODIES = 5 #primary text
MAX_TITLES = 5 #headline
MAX_DESCRIPTIONS = 5 #description
MAX_IMAGES = 10
MAX_VIDEOS = 10

# Meta asset character limits
MAX_PRIMARY_TEXT_CHARS = 125
MAX_HEADLINE_CHARS = 40
MAX_DESCRIPTION_CHARS = 30

VALID_CALL_TO_ACTION_TYPES = {
    "LEARN_MORE",       # general awareness / traffic
    "SHOP_NOW",         # ecommerce
    "SIGN_UP",          # lead generation / registration
    "SUBSCRIBE",        # subscriptions
    "CONTACT_US",       # service businesses
    "APPLY_NOW",        # jobs / admissions
    "BOOK_NOW",         # appointments / reservations
    "DOWNLOAD",         # app installs / content
    "GET_OFFER",        # promotions / discounts
    "WATCH_MORE",       # video content
    "GET_DIRECTIONS",   # local businesses
    "CALL_NOW",         # phone calls
    "SEND_MESSAGE",     # messaging campaigns
    "OPEN_LINK",        # generic link
    "NO_BUTTON",        # no CTA button
}

# CTA types allowed by Meta specifically for Lead Ads (ON_AD destination)
VALID_LEAD_AD_CTA_TYPES = {
    "APPLY_NOW", "DOWNLOAD", "GET_QUOTE",
    "LEARN_MORE", "SIGN_UP", "SUBSCRIBE"
}