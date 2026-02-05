import httpx

_client: httpx.AsyncClient | None = None


def init_http_client():
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(60, connect=10),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )


async def close_http_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialized")
    return _client
