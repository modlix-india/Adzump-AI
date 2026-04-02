import base64
import os
from typing import List

import httpx

import structlog

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT = 60.0

logger = structlog.get_logger(__name__)


async def text_completion(
    prompt: str,
    model: str = "gemini-2.0-flash",
) -> str:
    """
    Generate text completion using Gemini REST API.
    """
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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
    aspect_ratio: str = "1:1",
    image_parts: List[bytes] | None = None,
) -> List[bytes]:
    """
    Returns raw image BYTES.
    """
    url = f"{GEMINI_BASE_URL}/{model}:generateContent"

    parts = [{"text": prompt}]
    if image_parts:
        for img in image_parts:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(img).decode("utf-8"),
                    }
                }
            )

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["Image"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            },
        },
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
        )
        response.raise_for_status()

    data = response.json()
    candidates = data.get("candidates", [])
    logger.warning(
        "Gemini image generation response received",
        num_candidates=len(candidates),
        has_data=bool(data),
        # Log the first candidate's safety ratings or text if no images
        first_candidate_keys=list(candidates[0].keys()) if candidates else None,
        safety_ratings=candidates[0].get("safetyRatings") if candidates else None,
    )

    images: List[bytes] = []

    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        # Log if we got text instead of image
        for part in parts:
            if "text" in part:
                logger.warning(
                    "Gemini returned TEXT instead of image", text=part["text"][:100]
                )

            inline_data = part.get("inlineData", {})
            mime_type = inline_data.get("mimeType", "")
            if mime_type in ("image/png", "image/jpeg"):
                raw = inline_data.get("data", "")
                images.append(base64.b64decode(raw))
                if len(images) >= n:
                    return images

    if not images:
        logger.error("No images found in Gemini response", full_response=data)

    return images
