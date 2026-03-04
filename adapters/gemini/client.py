import base64
import os
from typing import List

import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


async def text_completion(
    prompt: str,
    model: str = "gemini-2.0-flash",
) -> str:
    """
    Generate text completion using Gemini REST API.
    """
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
        response.raise_for_status()

    data = response.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected Gemini response structure: {data}") from e


async def generate_images(
    prompt: str,
    n: int = 1,
    model: str = "gemini-2.5-flash-image",
) -> List[bytes]:
    """
    Returns raw image BYTES.
    """
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"
    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
        response.raise_for_status()

    data = response.json()
    images: List[bytes] = []

    candidates = data.get("candidates", [])
    for candidate in candidates:
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData", {})
            mime_type = inline_data.get("mimeType", "")
            if mime_type in ("image/png", "image/jpeg"):
                raw = inline_data.get("data", "")
                images.append(base64.b64decode(raw))
                if len(images) >= n:
                    return images

    return images
