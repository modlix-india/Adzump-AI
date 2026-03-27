"""
Session Store - Shared session storage for services.

A cleaner, class-based session store that can be used by new services.
Easy to swap to Redis for production scalability.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from structlog import get_logger

logger = get_logger(__name__)

SESSION_TIMEOUT = timedelta(minutes=30)
MAX_EVENT_LOG_SIZE = 500


class SessionStore:
    """
    Generic session store with expiration handling.

    Stores arbitrary dict data per session. Services handle
    their own data schema.
    """

    def __init__(self, timeout: timedelta = SESSION_TIMEOUT):
        self._sessions: dict[str, dict] = {}
        self._timeout = timeout
        self._cancelled: dict[str, bool] = {}
        self._event_logs: dict[str, list[tuple[int, str]]] = {}

    def create(self, initial_data: Optional[dict] = None) -> str:
        """Create a new session. Returns session ID."""
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "data": initial_data or {},
            "last_activity": datetime.now(timezone.utc),
        }
        logger.info("Session created", session_id=session_id)
        return session_id

    def get(self, session_id: str, update_activity: bool = True) -> Optional[dict]:
        """
        Get session data by ID.
        Returns None if session doesn't exist or has expired.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        current_time = datetime.now(timezone.utc)
        if current_time - session["last_activity"] > self._timeout:
            logger.info("Session expired", session_id=session_id)
            self.delete(session_id)
            return None

        if update_activity:
            session["last_activity"] = current_time

        return dict(session["data"])

    def update(self, session_id: str, data: dict) -> bool:
        """Replace session data entirely. Returns False if session doesn't exist."""
        if session_id not in self._sessions:
            return False

        self._sessions[session_id]["data"] = data
        self._sessions[session_id]["last_activity"] = datetime.now(timezone.utc)
        return True

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if existed."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._cancelled.pop(session_id, None)
            self.clear_event_log(session_id)
            logger.info("Session deleted", session_id=session_id)
            return True
        return False

    def exists(self, session_id: str) -> bool:
        """Check if session exists (without updating activity)."""
        return session_id in self._sessions

    def get_last_activity(self, session_id: str) -> Optional[datetime]:
        """Get the last activity timestamp for a session."""
        session = self._sessions.get(session_id)
        return session["last_activity"] if session else None

    def mark_cancelled(self, session_id: str) -> bool:
        """Mark session for cancellation. Returns False if session doesn't exist."""
        if session_id not in self._sessions:
            return False
        self._cancelled[session_id] = True
        return True

    def is_cancelled(self, session_id: str) -> bool:
        """Check if session has been marked for cancellation."""
        return self._cancelled.get(session_id, False)

    def clear_cancelled(self, session_id: str) -> None:
        """Clear cancellation flag."""
        self._cancelled.pop(session_id, None)

    def append_event(self, session_id: str, seq: int, frame: str) -> None:
        """Append an SSE frame to the session's event log for reconnection replay."""
        log = self._event_logs.setdefault(session_id, [])
        log.append((seq, frame))
        if len(log) > MAX_EVENT_LOG_SIZE:
            log.pop(0)

    def get_events_after(self, session_id: str, after_id: int) -> list[str]:
        """Return SSE frames with sequence number > after_id."""
        return [frame for seq, frame in self._event_logs.get(session_id, []) if seq > after_id]

    def clear_event_log(self, session_id: str) -> None:
        """Remove all stored events for a session."""
        self._event_logs.pop(session_id, None)


# Singleton instance
_default_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Get the shared session store instance."""
    global _default_store
    if _default_store is None:
        _default_store = SessionStore()
    return _default_store
