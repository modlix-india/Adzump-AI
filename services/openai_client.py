from functools import lru_cache
from openai import AsyncOpenAI
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=OPENAI_API_KEY)

async def chat_completion(messages: list, model: str = "gpt-4.1") -> str:
    client = get_client()
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return (response.choices[0].message.content or "").strip()