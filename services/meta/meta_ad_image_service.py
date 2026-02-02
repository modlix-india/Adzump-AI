from fastapi import HTTPException
from services.genai_client import generate_images


class MetaAdImageService:

    @staticmethod
    async def generate_image(image_prompt: str) -> str:
        images = await generate_images(
            prompt=image_prompt,
            n=1
        )

        if not images or not images[0]:
            raise HTTPException(
                status_code=500,
                detail="Image generation failed: no image returned"
            )

        return images[0]
