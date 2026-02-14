from functools import lru_cache
from openai import AsyncOpenAI
import os
from typing import List

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


async def chat_completion(messages: list, model: str = "gpt-4.1", **kwargs):
    client = get_client()
    response = await client.chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    return response


async def generate_embeddings(
    texts: List[str], model: str = "text-embedding-3-small"
) -> List[List[float]]:
    """Generate embeddings for a list of texts."""
    client = get_client()
    response = await client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]
