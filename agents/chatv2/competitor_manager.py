"""Background competitor-find task manager. One job per session, fire-and-forget."""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from structlog import get_logger

logger = get_logger(__name__)


@dataclass
class CompetitorJob:
    """Tracks one background competitor-find per session."""

    task: asyncio.Task
    result: Optional[list[dict]] = field(default=None)
    error: Optional[str] = field(default=None)


class CompetitorTaskManager:
    """Manages background competitor-find tasks, one per session."""

    def __init__(self) -> None:
        self._jobs: dict[str, CompetitorJob] = {}

    def start_find(self, session_id: str, website_summary: dict) -> None:
        """Fire background competitor find. No-op if already running/completed."""
        if session_id in self._jobs:
            return

        task = asyncio.create_task(self._run(session_id, website_summary))
        self._jobs[session_id] = CompetitorJob(task=task)
        logger.info("competitor_find_started", session_id=session_id)

    def get_result_if_ready(self, session_id: str) -> Optional[list[dict]]:
        """Return competitor list if done. Non-blocking."""
        job = self._jobs.get(session_id)
        if job and job.task.done() and job.result is not None:
            return job.result
        return None

    def get_error(self, session_id: str) -> Optional[str]:
        """Return error message if find failed. Non-blocking."""
        job = self._jobs.get(session_id)
        if job and job.task.done() and job.error:
            return job.error
        return None

    def cleanup(self, session_id: str) -> None:
        """Cancel and remove job for a session."""
        job = self._jobs.pop(session_id, None)
        if job and not job.task.done():
            job.task.cancel()

    async def _run(self, session_id: str, website_summary: dict) -> None:
        from agents.chatv2.competitor_agent import find_competitors

        try:
            result = await find_competitors(website_summary)
            job = self._jobs.get(session_id)
            if job:
                job.result = result
                logger.info(
                    "competitor_find_completed",
                    session_id=session_id,
                    count=len(result),
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "competitor_find_failed", session_id=session_id, error=str(e)
            )
            job = self._jobs.get(session_id)
            if job:
                job.error = str(e)


_manager: Optional[CompetitorTaskManager] = None


def get_competitor_task_manager() -> CompetitorTaskManager:
    global _manager
    if _manager is None:
        _manager = CompetitorTaskManager()
    return _manager
