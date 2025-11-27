from enum import Enum

class FeedbackAction(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class RejectionCategory(str, Enum):
    IRRELEVANT = "irrelevant"
    TOO_BROAD = "too_broad"
    TOO_SPECIFIC = "too_specific"
    WRONG_LOCATION = "wrong_location"
    WRONG_INTENT = "wrong_intent"
    COMPETITOR = "competitor"
    LOW_VALUE = "low_value"
    DUPLICATE = "duplicate"
    BRAND_MISMATCH = "brand_mismatch"
    OTHER = "other"

