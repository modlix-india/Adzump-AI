from datetime import datetime, timedelta
from fastapi import HTTPException

from agents.meta.payload_builders.adset_builder.targeting_constructor import build_targeting
from agents.meta.payload_builders.adset_builder.promoted_object_constructor import build_promoted_object
from agents.meta.utils.utils import build_name , normalize_time
from agents.meta.payload_builders.constants import (
    VALID_BUDGET_TYPES,
    MIN_DAILY_BUDGET_INR,
    MIN_LIFETIME_BUDGET_INR,
    INR_TO_MINOR_UNIT,
    SCHEDULE_BUFFER_SECONDS,
    BID_STRATEGIES_REQUIRING_BID_AMOUNT,
    VALID_BILLING_EVENTS,
    OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP
)
#  NAME GENERATOR 
def generate_adset_name(business_name: str) -> str:
    if not business_name:
        raise HTTPException(status_code=400, detail="business_name is required for adset naming")
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M")
    return f"{business_name} adset {timestamp}"


#  BUDGET NORMALIZER 

def normalize_budget(budget: dict) -> dict:
    """
    Converts INR → Meta minor units
    and validates minimum budget.
    Returns dict with either daily_budget or lifetime_budget key.
    """
    if not budget:
        raise HTTPException(status_code=400, detail="Budget is required for adset")

    amount = budget.get("amount")
    budget_type = budget.get("type")

    if amount is None:
        raise HTTPException(status_code=400, detail="Budget amount is required")

    if not isinstance(amount, (int, float)) or amount <= 0:
        raise HTTPException(status_code=400, detail="Budget amount must be a positive number")

    if not budget_type:
        raise HTTPException(status_code=400, detail="Budget type is required")

    if budget_type not in VALID_BUDGET_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid budget type '{budget_type}'. Must be one of {sorted(VALID_BUDGET_TYPES)}"
        )

    if budget_type == "DAILY" and amount < MIN_DAILY_BUDGET_INR:
        raise HTTPException(status_code=400, detail=f"Minimum daily budget is ₹{MIN_DAILY_BUDGET_INR}")

    if budget_type == "LIFETIME" and amount < MIN_LIFETIME_BUDGET_INR:
        raise HTTPException(status_code=400, detail=f"Minimum lifetime budget is ₹{MIN_LIFETIME_BUDGET_INR}")

    minor_units = int(amount * INR_TO_MINOR_UNIT)

    if budget_type == "DAILY":
        return {"daily_budget": minor_units}

    return {"lifetime_budget": minor_units}

 
#  SCHEDULE VALIDATOR
def validate_schedule(start_time: str, end_time: str):
    """
    Validates normalized time strings from normalize_time.
    Expects Meta format: YYYY-MM-DDTHH:MM:SS±HHMM
    """
    if not start_time and end_time:
        raise HTTPException(
            status_code=400,
            detail="start_time is required when end_time is provided"
        )

    if not start_time:
        return

    try:
        start_dt = datetime.fromisoformat(start_time)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid start_time format")

    if start_dt < datetime.now(start_dt.tzinfo) + timedelta(seconds=SCHEDULE_BUFFER_SECONDS):
        raise HTTPException(
            status_code=400,
            detail="start_time must be at least 60 seconds in the future"
        )

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid end_time format")

        if end_dt <= start_dt:
            raise HTTPException(
                status_code=400,
                detail="end_time must be after start_time"
            )

def validate_bidding(bidding: dict):
    if not bidding:
        raise HTTPException(status_code=400, detail="Bidding is required for adset")

    billing_event     = bidding.get("billing_event")
    optimization_goal = bidding.get("optimization_goal")

    # Validate billing_event
    if not billing_event:
        raise HTTPException(
            status_code=400,
            detail=f"bidding.billing_event is required. Must be one of: {sorted(VALID_BILLING_EVENTS)}"
        )

    if billing_event not in VALID_BILLING_EVENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid billing_event '{billing_event}'. Must be one of: {sorted(VALID_BILLING_EVENTS)}"
        )

    # Validate optimization_goal
    if not optimization_goal:
        raise HTTPException(
            status_code=400,
            detail=f"bidding.optimization_goal is required. Must be one of: {sorted(OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP.keys())}"
        )

    if optimization_goal not in OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid optimization_goal '{optimization_goal}'. Must be one of: {sorted(OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP.keys())}"
        )

    # Validate bid_strategy requires bid_amount
    bid_strategy = bidding.get("bid_strategy")
    bid_amount   = bidding.get("bid_amount")

    if bid_strategy in BID_STRATEGIES_REQUIRING_BID_AMOUNT and bid_amount is None:
        raise HTTPException(
            status_code=400,
            detail=f"bid_amount is required for bid_strategy '{bid_strategy}'"
        )

#  PROMOTED OBJECT VALIDATOR 
def validate_promoted_object_match(optimization_goal: str, promoted_object: dict):
    """
    Validates that promoted_object type matches the optimization_goal.
    """

    # Unknown optimization goal — skip validation, let Meta handle it
    if optimization_goal not in OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP:
        return

    expected_type = OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP.get(optimization_goal)

    # No promoted_object needed for this optimization goal
    if expected_type is None:
        if promoted_object:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"promoted_object should not be provided for optimization_goal '{optimization_goal}'. "
                    f"Optimization goals that do not require promoted_object: "
                    f"{[goal for goal, ptype in OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP.items() if ptype is None]}"
                )
            )
        return

    # promoted_object required but not provided
    if not promoted_object:
        raise HTTPException(
            status_code=400,
            detail=(
                f"promoted_object is required for optimization_goal '{optimization_goal}'. "
                f"Expected promoted_object type: '{expected_type}'"
            )
        )

    # promoted_object type mismatch
    actual_type = promoted_object.get("type")

    if actual_type != expected_type:
        raise HTTPException(
            status_code=400,
            detail=(
                f"optimization_goal '{optimization_goal}' requires promoted_object type '{expected_type}' "
                f"but got '{actual_type}'. "
                f"Full reference — optimization_goal → promoted_object type: "
                f"{OPTIMIZATION_GOAL_PROMOTED_OBJECT_MAP}"
            )
        )


#  ADSET BUILDER 
def build_adset_payload(adset: dict) -> dict:
    if not adset:
        raise HTTPException(status_code=400, detail="Adset payload is required")

    # Name
    if not adset.get("name"):
        raise HTTPException(status_code=400, detail="Adset name is required")
    name = build_name(adset["name"], "adset")   

    # Budget
    budget_fields = normalize_budget(adset.get("budget"))

    # Schedule
    start_time_raw = adset.get("schedule", {}).get("start_time")
    end_time_raw = adset.get("schedule", {}).get("end_time")
    start_time = normalize_time(start_time_raw)
    end_time = normalize_time(end_time_raw)
    validate_schedule(start_time, end_time)

    # Lifetime budget requires end_time
    if "lifetime_budget" in budget_fields and not end_time:
        raise HTTPException(status_code=400, detail="end_time is required when using lifetime_budget")

    # Bidding
    bidding = adset.get("bidding")
    validate_bidding(bidding)

    # Validate promoted_object matches optimization_goal
    validate_promoted_object_match(
        bidding["optimization_goal"],
        adset.get("promoted_object")
    )

    # Targeting guard
    if not adset.get("targeting"):
        raise HTTPException(status_code=400, detail="Targeting is required for adset")

    # Build promoted_object if provided
    promoted_object = None
    if adset.get("promoted_object"):
        promoted_object = build_promoted_object(adset["promoted_object"])

    # Build payload
    payload = {
        "name": name,
        "destination_type": adset.get("destination_type"),
        "is_dynamic_creative": adset.get("is_dynamic_creative"),
        "start_time": start_time,
        "end_time": end_time,
        "billing_event": bidding["billing_event"],
        "optimization_goal": bidding["optimization_goal"],
        "bid_strategy": bidding.get("bid_strategy"),
        "bid_amount": bidding.get("bid_amount"),
        "targeting": build_targeting(adset["targeting"]),
        "promoted_object": promoted_object,
        "status": adset.get("status", "PAUSED"),
        **budget_fields
    }

    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }