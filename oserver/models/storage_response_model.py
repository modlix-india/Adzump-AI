from pydantic import BaseModel
from typing import Any,Optional

class StorageResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

    @property
    def content(self) -> list:
        if not self.result:
            return []
        return self.result[0].get("result", {}).get("result", {}).get("content", [])
