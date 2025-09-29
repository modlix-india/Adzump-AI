from fastapi import FastAPI
from apis.ads_api import router as ads_router
from apis.chat_api import router as chat_router
from dotenv import load_dotenv
load_dotenv()  # No-op in prod if no .env is present

app = FastAPI(title="Ads AI: Automate, Optimize, Analyze")

app.include_router(ads_router)
app.include_router(chat_router)