import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from structlog import get_logger  # type: ignore

from config.scraper_config import ScraperConfig

logger = get_logger(__name__)


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int = ScraperConfig.MAX_CONCURRENT_REQUESTS):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._lock = asyncio.Lock()

        logger.info("[ConcurrencyLimiter] Initialized", max_concurrent=max_concurrent)

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[None, None]:
        async with self._semaphore:
            async with self._lock:
                self._active_count += 1

            try:
                yield
            finally:
                async with self._lock:
                    self._active_count -= 1

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def available_slots(self) -> int:
        return self.max_concurrent - self._active_count

    @property
    def stats(self) -> dict:
        return {
            "max_concurrent": self.max_concurrent,
            "active": self._active_count,
            "available": self.available_slots,
        }
