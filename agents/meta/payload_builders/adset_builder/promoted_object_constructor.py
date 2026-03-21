from fastapi import HTTPException

from agents.meta.payload_builders.constants import VALID_PIXEL_EVENTS, VALID_STORE_PATTERNS

def build_promoted_object(promoted_object: dict) -> dict:
    if not promoted_object:
        raise HTTPException(status_code=400, detail="promoted_object is required for adset")

    obj_type = promoted_object.get("type")

    if not obj_type:
        raise HTTPException(status_code=400, detail="promoted_object.type is required")

    if obj_type == "PAGE":
        page_id = promoted_object.get("page_id")
        if not page_id:
            raise HTTPException(status_code=400, detail="promoted_object.page_id is required for PAGE type")
        return {"page_id": str(page_id)}

    if obj_type == "PIXEL":
        pixel_id = promoted_object.get("pixel_id")
        event = promoted_object.get("event")

        if not pixel_id:
            raise HTTPException(status_code=400, detail="promoted_object.pixel_id is required for PIXEL type")

        if not event:
            raise HTTPException(status_code=400, detail="promoted_object.event is required for PIXEL type")

        if event not in VALID_PIXEL_EVENTS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pixel event '{event}'. Must be one of {sorted(VALID_PIXEL_EVENTS)}"
            )

        return {
            "pixel_id": str(pixel_id),
            "custom_event_type": event
        }

    if obj_type == "APP":
        application_id = promoted_object.get("application_id")
        object_store_url = promoted_object.get("object_store_url")

        if not application_id:
            raise HTTPException(status_code=400, detail="promoted_object.application_id is required for APP type")

        if not object_store_url:
            raise HTTPException(status_code=400, detail="promoted_object.object_store_url is required for APP type")

        if not any(pattern in object_store_url for pattern in VALID_STORE_PATTERNS):
            raise HTTPException(
                status_code=400,
                detail="object_store_url must be from App Store (apps.apple.com) or Google Play (play.google.com)"
            )

        return {
            "application_id": str(application_id),
            "object_store_url": object_store_url
        }

    raise HTTPException(status_code=400, detail=f"Unsupported promoted_object type: {obj_type}")