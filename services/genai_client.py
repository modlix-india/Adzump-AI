from functools import lru_cache
import os
from typing import List
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


@lru_cache(maxsize=1)
def get_client():
    return genai.Client(api_key=GEMINI_API_KEY)


async def text_completion(
    prompt: str,
    model: str = "gemini-2.0-flash"
) -> str:
    client = get_client()

    response = client.models.generate_content(
        model=model,
        contents=[prompt],
    )

    return response.text


async def generate_images(
    prompt: str,
    n: int = 1,
    model: str = "gemini-2.5-flash-image"
) -> List[bytes]:
    """
    Generate images using Gemini image model.
    Returns raw image BYTES.
    """

    client = get_client()

    response = client.models.generate_content(
        model=model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    images: List[bytes] = []

    if not response or not response.candidates:
        return images

    for candidate in response.candidates:
        if not candidate.content or not candidate.content.parts:
            continue 

        for part in candidate.content.parts:
            if (
                part.inline_data
                and part.inline_data.mime_type in ("image/png", "image/jpeg")
            ):
                images.append(part.inline_data.data)

                if len(images) >= n:
                    return images

    return images
