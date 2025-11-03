from pydantic import BaseModel
from typing import Any,Optional

class StorageResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
