import asyncio
import contextlib
from datetime import datetime, timezone, timedelta


SESSION_TIMEOUT = timedelta(minutes=30)

# In-memory store
sessions = {}

async def remove_expired_sessions():
    while True:
        now = datetime.now(timezone.utc)
        expired = [sid for sid, data in sessions.items() if now - data["last_activity"] > SESSION_TIMEOUT]
        for sid in expired:
            del sessions[sid]
            print(f"Session {sid} expired and removed.")
        await asyncio.sleep(300)
 