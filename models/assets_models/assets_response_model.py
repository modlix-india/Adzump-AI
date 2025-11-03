from pydantic import BaseModel
from typing import Any, Optional

class AssetResponse(BaseModel):
    success: bool
    result: Optional[Any]
    error: Optional[str] = None