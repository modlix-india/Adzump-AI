from agents.meta.utils.payload_helpers import build_name
from core.models.meta import AdCreationStage


def build_ad_payload(ad: dict) -> dict:
    return {
        "name": build_name(ad["name"], AdCreationStage.AD),
        "creative": {},  # creative_id injected later by orchestrator
        "status": ad.get("status", "PAUSED"),
    }
