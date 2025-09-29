from fastapi import APIRouter
from services import chat_service

router = APIRouter(prefix="/api/ds/chat", tags=["chat"])

@router.post("/start-session")
async def start_session():
    return chat_service.start_session()

@router.post("/{session_id}")
async def chat(session_id: str, message: str):
    return await chat_service.process_chat(session_id, message)

@router.post("/end-session/{session_id}")
async def end_session(session_id: str):
    return chat_service.end_session(session_id)