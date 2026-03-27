import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from openai import AsyncOpenAI
import os
from typing import List

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MAX_CONCURRENT_LLM_CALLS = 10
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


async def chat_completion(messages: list, model: str = "gpt-4.1", **kwargs):
    async with _semaphore:
        client = get_client()
        response = await client.chat.completions.create(
            model=model, messages=messages, **kwargs
        )
        return response


async def chat_completion_stream(
    messages: list, model: str = "gpt-4.1", **kwargs
) -> AsyncIterator[str]:
    """Stream chat completion, yielding content delta strings."""
    async with _semaphore:
        client = get_client()
        stream = await client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content


async def generate_embeddings(
    texts: List[str], model: str = "text-embedding-3-small"
) -> List[List[float]]:
    """Generate embeddings for a list of texts."""
    async with _semaphore:
        client = get_client()
        response = await client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]
