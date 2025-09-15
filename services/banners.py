# import os
# import json
# from openai import OpenAI
# from dotenv import load_dotenv
# from concurrent.futures import ThreadPoolExecutor
# import asyncio

# # Load env
# load_dotenv()
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# executor = ThreadPoolExecutor()

# AD_SIZES = [
#     {"width": 1024, "height": 1024},
#     {"width": 1024, "height": 1536},
#     {"width": 1536, "height": 1024},
# ]

# def generate_banner_sync(data, size):
#     prompt = f"""
#     You are an AI designer. Generate a **Google Display ad banner**:

#     Website JSON summary:
#     {json.dumps(data, indent=2)}

#     Banner size: {size['width']}x{size['height']} px
#     Style: professional, modern, visually attractive
#     Text: concise, catchy messaging based on the website data
#     Return a single image URL or base64 if possible.
#     """

#     response = client.images.generate(
#         model="gpt-image-1",
#         prompt=prompt,
#         size=f"{size['width']}x{size['height']}"
#     )

#     return response.data[0].url if response.data else None


# async def generate_banners(data):
#     loop = asyncio.get_running_loop()
#     banners = []

#     for size in AD_SIZES:
#         url = await loop.run_in_executor(executor, generate_banner_sync, data, size)
#         banners.append({
#             "width": size["width"],
#             "height": size["height"],
#             "image_url": url
#         })
#     return banners


# import os
# import json
# import requests
# from dotenv import load_dotenv
# from concurrent.futures import ThreadPoolExecutor
# import asyncio

# # Load env
# load_dotenv()
# # deepai_api_key = os.getenv("DEEP_AI_KEY")
# STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# executor = ThreadPoolExecutor()

# AD_SIZES = [
#     {"width": 1024, "height": 1024},
#     {"width": 1024, "height": 1536},
#     {"width": 1536, "height": 1024},
# ]

# def generate_banner_sync(data, size):
#     prompt = f"""
#     You are an AI designer. Generate a **Google Display ad banner**:

#     Website JSON summary:
#     {json.dumps(data, indent=2)}

#     Banner size: {size['width']}x{size['height']} px
#     Style: professional, modern, visually attractive
#     Text: concise, catchy messaging based on the website data
#     """

#     # Call DeepAI API
#     response = requests.post(
#         "https://api.deepai.org/api/stable-diffusion",   # ✅ use stable-diffusion
#         data={"text": prompt},
#         headers={"api-key": deepai_api_key}
#     )

#     result = response.json()
#     print("🔍 DeepAI Response:", result)  # Debug
#     return result.get("output_url")   # DeepAI returns this

# async def generate_banners(data):
#     loop = asyncio.get_running_loop()
#     banners = []

#     for size in AD_SIZES:
#         url = await loop.run_in_executor(executor, generate_banner_sync, data, size)
#         banners.append({
#             "width": size["width"],
#             "height": size["height"],
#             "image_url": url
#         })
#     return banners


import os
import json
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import asyncio
import base64

# Load env
load_dotenv()
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

executor = ThreadPoolExecutor()

AD_SIZES = [
    {"label": "square", "aspect_ratio": "1:1"},     # 1024x1024
    # {"label": "landscape", "aspect_ratio": "3:2"},  # 1536x1024
    # {"label": "portrait", "aspect_ratio": "2:3"},   # 1024x1536
]

def generate_banner_sync(data, size):
    prompt = f"""
    You are an AI designer. Generate a **Google Display ad banner**:

    Website JSON summary:
    {json.dumps(data, indent=2)}

    Banner aspect ratio: {size['aspect_ratio']}
    Style: professional, modern, visually attractive
    Text: concise, catchy messaging based on the website data
    """

    url = "https://api.stability.ai/v2beta/stable-image/generate/core"

    headers = {
        "Authorization": f"Bearer {STABILITY_API_KEY}",
        "Accept": "application/json"
    }

    files = {
        "prompt": (None, prompt),
        "output_format": (None, "png"),
        "aspect_ratio": (None, size["aspect_ratio"]),
    }

    response = requests.post(url, headers=headers, files=files)

    if response.status_code == 200:
        data = response.json()
        # Stability returns base64 → convert to data URL
        if "image" in data:
            return f"data:image/png;base64,{data['image']}"
        else:
            return None
    else:
        print("Error:", response.text)
        return None


async def generate_banners(data):
    loop = asyncio.get_running_loop()
    banners = []

    for size in AD_SIZES:
        img = await loop.run_in_executor(executor, generate_banner_sync, data, size)
        banners.append({
            "aspect_ratio": size["aspect_ratio"],
            "label": size["label"],
            "image": img
        })
    return banners