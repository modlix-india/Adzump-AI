from fastapi import APIRouter, Query
from typing import Optional
from services import chat_service

router = APIRouter(prefix="/api/ds/chat", tags=["chat"])

@router.post("/start-session")
async def start_session():
    return await chat_service.start_session()

@router.post("/{session_id}")
async def chat(session_id: str, message: str, clientCode: Optional[str] = Query(None)):
    return await chat_service.process_chat(session_id, message, clientCode)

@router.post("/end-session/{session_id}")
async def end_session(session_id: str):
    return await chat_service.end_session(session_id)