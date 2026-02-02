import httpx
import asyncio
import structlog
from typing import Optional

logger = structlog.get_logger(__name__)

_httpx_client: Optional[httpx.AsyncClient] = None
_clinet_lock = asyncio.Lock()

HTTP_TIMEOUT = 60.0
MAX_CONNECTIONS = 100
MAX_KEEPALIVE = 20


async def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    logger.info("Getting httpx client")
    if _httpx_client is None:
        async with _clinet_lock:
            # Double check after acquiring the lock
            if _httpx_client is None:
                logger.info("Creating new httpx client")
                _httpx_client = httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT,
                    limits=httpx.Limits(
                        max_connections=MAX_CONNECTIONS,
                        max_keepalive_connections=MAX_KEEPALIVE,
                    ),
                    http2=True,
                )
    return _httpx_client


async def close_httpx_client():
    global _httpx_client
    logger.info("Closing httpx client")
    async with _clinet_lock:
        # Double check after acquiring the lock
        if _httpx_client is not None:
            await _httpx_client.aclose()
            _httpx_client = None
