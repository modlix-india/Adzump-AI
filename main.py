import asyncio
import sys
from fastapi import FastAPI
from controllers.ads_controller import router as ads_router
from controllers.chatbot import router as ai_router


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI(title="Ad Generator API")


app.include_router(ads_router, prefix="/api/ads", tags=["ads"])
app.include_router(ai_router, prefix="/adzumpai/chatbot", tags=["aichat"])


