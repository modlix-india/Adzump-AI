import httpx
import asyncio
import logging
from exceptions.custom_exceptions import StorageException
from oserver.utils.helpers import get_base_url

logger = logging.getLogger(__name__)

class BaseAPIService:
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_MAX_RETRIES = 2

    def __init__(self):
        self.base_url = get_base_url().rstrip("/")
        self.timeout = self.DEFAULT_TIMEOUT
        self.max_retries = self.DEFAULT_MAX_RETRIES

    async def request(self, method: str, url: str, *, headers=None, payload=None, files=None)-> dict | str:
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    if method == "GET":
                        response = await client.get(url, headers=headers)
                    elif method == "POST":
                        response = await client.post(url, headers=headers, json=payload, files=files)
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
                raise StorageException(f"HTTP error {status}: {text}")
