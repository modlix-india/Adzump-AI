from fastapi import APIRouter
from services import chatbot_service

router = APIRouter()

from pydantic import BaseModel

class ChatRequest(BaseModel):
    session_id: str
    message: str

@router.post("/start-session")
async def start_session():
    return chatbot_service.start_session()

@router.post("/chat")
async def chat(req: ChatRequest):
    return await chatbot_service.process_chat(req.session_id, req.message)

@router.post("/end-session/{session_id}")
async def end_session(session_id: str):
    return chatbot_service.end_session(session_id)
 