from fastapi import FastAPI
from dotenv import load_dotenv
load_dotenv()
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from apis.assets_api import router as assets_router
from apis.business_api import router as business_router
from dotenv import load_dotenv
load_dotenv()  # No-op in prod if no .env is present

app = FastAPI(title="Ads AI: Automate, Optimize, Analyze")

app.include_router(ads_router)
app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(business_router)