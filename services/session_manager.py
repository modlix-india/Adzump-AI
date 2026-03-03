# TODO: migrate to new architecture (services/ → core/infrastructure/)
import asyncio
import contextlib
from datetime import datetime, timezone, timedelta

from exceptions.custom_exceptions import BusinessValidationException

SESSION_TIMEOUT = timedelta(minutes=30)

# In-memory store
sessions: dict[str, dict] = {}


def get_website_url(session_id: str) -> str:
    if session_id not in sessions:
        raise BusinessValidationException(f"Session not found: {session_id}")
    campaign_data = sessions[session_id].get("campaign_data", {})
    website_url = campaign_data.get("websiteURL")
    if not website_url:
        raise BusinessValidationException("Session missing websiteURL")
    return website_url

async def remove_expired_sessions():
    while True:
        now = datetime.now(timezone.utc)
        expired = [sid for sid, data in sessions.items() if now - data["last_activity"] > SESSION_TIMEOUT]
        for sid in expired:
            del sessions[sid]
            print(f"Session {sid} expired and removed.")
        await asyncio.sleep(300)
 