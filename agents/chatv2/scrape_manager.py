import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Optional

from structlog import get_logger

from models.business_model import WebsiteSummaryResponse

logger = get_logger(__name__)


@dataclass
class AuthParams:
    """Snapshot of auth credentials for background task."""

    access_token: str
    client_code: str
    x_forwarded_host: str
    x_forwarded_port: str


@dataclass
class ScrapeJob:
    """Tracks one background scrape per session."""

    url: str
    task: asyncio.Task
    result: Optional[WebsiteSummaryResponse] = field(default=None)
    error: Optional[str] = field(default=None)
    progress: asyncio.Queue = field(default_factory=asyncio.Queue)


class ScrapeTaskManager:
    """Manages background website scrape tasks, one per session."""

    def __init__(self) -> None:
        self._scrape_jobs: dict[str, ScrapeJob] = {}

    def start_scrape(self, session_id: str, url: str, auth: AuthParams) -> None:
        """Start a background scrape. Cancel existing if URL differs; no-op if same URL."""
        existing = self._scrape_jobs.get(session_id)
        if existing:
            if existing.url == url:
                logger.info(
                    "scrape_already_running",
                    session_id=session_id,
                    url=url,
                )
                return
            self._cancel_job(session_id, existing)

        task = asyncio.create_task(self._run_scrape(session_id, url, auth))
        self._scrape_jobs[session_id] = ScrapeJob(url=url, task=task)
        logger.info("background_scrape_started", session_id=session_id, url=url)

    def get_result_if_ready(self, session_id: str) -> Optional[WebsiteSummaryResponse]:
        """Return result if scrape is done. Non-blocking."""
        job = self._scrape_jobs.get(session_id)
        if job and job.task.done() and job.result:
            return job.result
        return None

    def get_error(self, session_id: str) -> Optional[str]:
        """Return error message if scrape failed. Non-blocking."""
        job = self._scrape_jobs.get(session_id)
        if job and job.task.done() and job.error:
            return job.error
        return None

    def has_active_scrape(self, session_id: str) -> bool:
        """Check if a scrape task is currently running for this session."""
        job = self._scrape_jobs.get(session_id)
        return job is not None and not job.task.done()

    async def subscribe_progress(
        self, session_id: str
    ) -> AsyncIterator[tuple[str, str, str]]:
        """Yield progress tuples in real-time. Exits when task completes and queue is empty."""
        job = self._scrape_jobs.get(session_id)
        if not job:
            return
        while True:
            if job.task.done() and job.progress.empty():
                break
            try:
                event = await asyncio.wait_for(job.progress.get(), timeout=0.5)
                yield event
            except asyncio.TimeoutError:
                if job.task.done():
                    break

    def drain_progress(self, session_id: str) -> list[tuple[str, str, str]]:
        """Return and clear all buffered progress events (non-blocking)."""
        job = self._scrape_jobs.get(session_id)
        if not job:
            return []
        events = []
        while not job.progress.empty():
            try:
                events.append(job.progress.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def cleanup(self, session_id: str) -> None:
        """Cancel and remove scrape job for a session."""
        job = self._scrape_jobs.pop(session_id, None)
        if job:
            self._cancel_job(session_id, job)

    async def _run_scrape(self, session_id: str, url: str, auth: AuthParams) -> None:
        from agents.scrape.scrape_agent import ScrapeAgent

        def on_progress(step: str, phase: str, message: str) -> None:
            job = self._scrape_jobs.get(session_id)
            if job and job.url == url:
                job.progress.put_nowait((step, phase, message))

        try:
            result = await ScrapeAgent().run(
                url=url,
                access_token=auth.access_token,
                client_code=auth.client_code,
                x_forwarded_host=auth.x_forwarded_host,
                x_forwarded_port=auth.x_forwarded_port,
                on_progress=on_progress,
            )
            job = self._scrape_jobs.get(session_id)
            if job and job.url == url:
                job.result = result
                logger.info(
                    "background_scrape_completed",
                    session_id=session_id,
                    url=url,
                    storage_id=result.storage_id,
                )
        except asyncio.CancelledError:
            logger.info("scrape_cancelled", session_id=session_id)
            raise
        except Exception as e:
            logger.warning(
                "background_scrape_failed", session_id=session_id, error=str(e)
            )
            job = self._scrape_jobs.get(session_id)
            if job and job.url == url:
                job.error = str(e)

    def _cancel_job(self, session_id: str, job: ScrapeJob) -> None:
        if not job.task.done():
            job.task.cancel()
            logger.info("previous_scrape_cancelled", session_id=session_id, url=job.url)
        self._scrape_jobs.pop(session_id, None)


_manager: Optional[ScrapeTaskManager] = None


def get_scrape_task_manager() -> ScrapeTaskManager:
    global _manager
    if _manager is None:
        _manager = ScrapeTaskManager()
    return _manager