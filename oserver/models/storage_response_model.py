from pydantic import BaseModel
from typing import Any, Optional


class StorageResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

    @property
    def content(self) -> list:
        """
        Extracts content from the response result.
        Handles both list-based results (paginated) and single object results.
        Optimized for robustness and consistency.
        """
        if not self.result:
            return []

        # Initial data from raw result
        data = self.result
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        # Standardize drilling into 'result' wrappers
        while isinstance(data, dict) and "result" in data:
            data = data["result"]

        if data is None:
            return []

        # Handle paginated wrapper (ReadPage)
        if isinstance(data, dict) and "content" in data:
            content_list = data["content"]
            return content_list if isinstance(content_list, list) else [content_list]

        # Handle single record or list of records (Read)
        return data if isinstance(data, list) else [data]
