from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from exceptions.handlers import setup_exception_handlers

app = FastAPI(title="Ads AI: Automate, Optimize, Analyze")

app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)


setup_exception_handlers(app)