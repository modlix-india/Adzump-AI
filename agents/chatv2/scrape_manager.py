import asyncio
from collections.abc import AsyncIterator, Callable
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
    progress_history: list = field(default_factory=list)
    partial_summary: Optional[dict] = field(default=None)


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

    def get_partial_summary(self, session_id: str) -> Optional[dict]:
        """Return partial summary if available (before scrape completes)."""
        job = self._scrape_jobs.get(session_id)
        if job and job.partial_summary:
            return job.partial_summary
        return None

    def has_active_scrape(self, session_id: str) -> bool:
        """Check if a scrape task is currently running for this session."""
        job = self._scrape_jobs.get(session_id)
        return job is not None and not job.task.done()

    async def subscribe_progress(
        self, session_id: str, *, wait_for_job: bool = False, wait_timeout: float = 60
    ) -> AsyncIterator[tuple[str, str, str]]:
        """Yield progress tuples in real-time. Exits when task completes and queue is empty.

        If *wait_for_job* is True, polls up to *wait_timeout* seconds for a job to appear
        (useful when the scrape is started mid-graph and subscribe is called before it exists).
        """
        job = self._scrape_jobs.get(session_id)
        if not job and wait_for_job:
            elapsed = 0.0
            while elapsed < wait_timeout:
                await asyncio.sleep(0.5)
                elapsed += 0.5
                job = self._scrape_jobs.get(session_id)
                if job:
                    break
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

    def get_progress_history(self, session_id: str) -> list[tuple[str, str, str]]:
        """Return all progress events seen so far (non-destructive)."""
        job = self._scrape_jobs.get(session_id)
        if not job:
            return []
        return list(job.progress_history)

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
        from agents.scrape.scrape_agent import scrape_agent
        from core.infrastructure.context import set_auth_context

        try:
            set_auth_context(
                access_token=auth.access_token,
                client_code=auth.client_code,
                x_forwarded_host=auth.x_forwarded_host,
                x_forwarded_port=auth.x_forwarded_port,
            )
            result = await scrape_agent.run(
                url=url,
                access_token=auth.access_token,
                client_code=auth.client_code,
                x_forwarded_host=auth.x_forwarded_host,
                x_forwarded_port=auth.x_forwarded_port,
                on_progress=self._make_progress_callback(session_id, url),
                on_data=self._make_data_callback(session_id, url),
            )
            job = self._scrape_jobs.get(session_id)
            if job and job.url == url:
                job.result = result
                # Mark the last scrape step as completed
                last_step = job.progress_history[-1][0] if job.progress_history else "save"
                job.progress_history.append((last_step, "end", "Analysis complete"))
                job.progress.put_nowait((last_step, "end", "Analysis complete"))
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

    def _make_progress_callback(
        self, session_id: str, url: str
    ) -> Callable[[str, str, str], None]:
        seen_steps: set[str] = set()

        def on_progress(step: str, phase: str, message: str) -> None:
            job = self._scrape_jobs.get(session_id)
            if job and job.url == url:
                # Auto-promote first event per step to "start" so the frontend
                # creates a new progress step entry in the sidebar.
                effective_phase = phase
                if phase == "update" and step not in seen_steps:
                    effective_phase = "start"
                seen_steps.add(step)
                job.progress_history.append((step, effective_phase, message))
                job.progress.put_nowait((step, effective_phase, message))

        return on_progress

    def _make_data_callback(
        self, session_id: str, url: str
    ) -> Callable[[str, dict], None]:
        def on_data(data_type: str, data: dict) -> None:
            job = self._scrape_jobs.get(session_id)
            if not job or job.url != url:
                return
            if data_type == "summary":
                job.partial_summary = data.get("payload", data)
                logger.info("partial_summary_captured", session_id=session_id)
            elif data_type == "summary_chunk":
                payload = data.get("payload", data)
                token = payload.get("token", "")
                if token:
                    # Forward chunk through progress queue with special sentinel
                    job.progress.put_nowait(("__summary_chunk__", "data", token))
            elif data_type == "screenshot":
                payload = data.get("payload", data)
                screenshot_url = payload.get("url", "")
                if screenshot_url:
                    job.progress.put_nowait(("__screenshot__", "data", screenshot_url))
                    logger.info("screenshot_forwarded", session_id=session_id)

        return on_data

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