from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Any, Dict, Optional


def success_response(data: Any):
    return JSONResponse(
        content={"success": True, "data": jsonable_encoder(data), "error": None},
        status_code=200,
    )


def error_response(
    message: str, details: Optional[Dict[str, Any]] = None, status_code: int = 500
):
    return JSONResponse(
        content={"success": False, "data": None, "error": message, "details": details},
        status_code=status_code,
    )
