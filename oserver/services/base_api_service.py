import httpx
import asyncio
import logging
from exceptions.custom_exceptions import StorageException

logger = logging.getLogger(__name__)

class BaseAPIService:

    def __init__(self, base_url: str, timeout: float = 30.0, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    async def _request(self, method: str, url: str, *, headers=None, json=None, files=None):
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    if method == "GET":
                        response = await client.get(url, headers=headers)
                    elif method == "POST":
                        response = await client.post(url, headers=headers, json=json, files=files)
                    else:
                        raise StorageException(f"Unsupported HTTP method: {method}")

                    response.raise_for_status()
                    try:
                        return response.json()
                    except Exception:
                        return response.text

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                attempt += 1
                if attempt <= self.max_retries:
                    await asyncio.sleep(0.5 * attempt)
                    continue

                status = getattr(getattr(e, "response", None), "status_code", 500)
                text = getattr(getattr(e, "response", None), "text", str(e))
                logger.error(f"{method} {url} failed: {text}")
                raise StorageException(detail=f"HTTP error {status}: {text}", status_code=status)
