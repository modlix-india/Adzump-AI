import asyncio
import functools
import random
from typing import Callable, Type, Union, Tuple

import structlog

logger = structlog.get_logger(__name__)


def async_retry(
    max_attempts: int = 3,
    initial_backoff: float = 2.0,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    retry_condition: Callable[[Exception], bool] | None = None,
    jitter: bool = True,
):
    """Retry an async function on failure with exponential backoff.

    Args:
        max_attempts:    Total attempts including the first call.
        initial_backoff: Seconds before first retry (doubles each attempt).
        exceptions:      Exception type(s) to retry on.
        retry_condition: Optional extra filter; return False to skip retry.
        jitter:          Add random 0-1s to prevent thundering herd.
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)

                except exceptions as e:
                    if retry_condition and not retry_condition(e):
                        raise

                    is_last = attempt == max_attempts - 1
                    if is_last:
                        logger.error(
                            "retry.exhausted",
                            func=func.__name__,
                            attempts=max_attempts,
                            error=str(e),
                        )
                        raise

                    delay = initial_backoff * (2**attempt)
                    if jitter:
                        delay += random.uniform(0, 1)

                    logger.warning(
                        "retry.backoff",
                        func=func.__name__,
                        attempt=attempt + 1,
                        next_retry_in=round(delay, 2),
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        return wrapper

    return decorator
