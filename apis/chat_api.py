from fastapi import APIRouter, Query
from services import chat_service
from services.adzump_session_bridge import create_session_from_adzump

router = APIRouter(prefix="/api/ds/chat", tags=["chat"])


@router.post("/start-session")
async def start_session():
    return await chat_service.start_session()


@router.post("/from-adzump-session/{adzump_session_id}")
async def start_session_from_adzump(adzump_session_id: str):
    """Pull an adzump session from nocode-ai and seed a ds session from it.

    Auth headers (Authorization, clientCode, X-Forwarded-Host/Port) must be
    on the incoming request — they're forwarded to nocode-ai so the user's
    own permission scope governs what data we can read.
    """
    return await create_session_from_adzump(adzump_session_id)


@router.post("/{session_id}")
async def chat(session_id: str, message: str, clientCode: str = Query(...)):
    return await chat_service.process_chat(session_id, message, clientCode)



@router.post("/end-session/{session_id}")
async def end_session(session_id: str):
    return await chat_service.end_session(session_id)

