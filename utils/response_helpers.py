from fastapi.responses import JSONResponse

def success_response(data: any):
    return JSONResponse(
        content={"success": True, "data": data, "error": None},
        status_code=200
    )

def error_response(message: str, status_code: int = 500):
    return JSONResponse(
        content={"success": False, "data": None, "error": message},
        status_code=status_code
    )