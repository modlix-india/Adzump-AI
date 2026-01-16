import httpx
import asyncio
import logging
from typing import Optional


logger = logging.getLogger(__name__)

# Module-level variables
_http_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()

# Configuration
HTTP_TIMEOUT = 60.0
MAX_CONNECTIONS = 100
MAX_KEEPALIVE = 20


async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    
    if _http_client is None:
        async with _client_lock:
            # Double-check after acquiring lock
            if _http_client is None:
                logger.info("Creating shared HTTP client")
                _http_client = httpx.AsyncClient(
                    timeout=HTTP_TIMEOUT,
                    limits=httpx.Limits(
                        max_connections=MAX_CONNECTIONS,
                        max_keepalive_connections=MAX_KEEPALIVE
                    ),
                    http2=True  # Enable HTTP/2 for better performance
                )
    
    return _http_client


async def close_http_client():
    global _http_client
    
    async with _client_lock:
        if _http_client is not None:
            logger.info("Closing shared HTTP client")
            await _http_client.aclose()
            _http_client = None



