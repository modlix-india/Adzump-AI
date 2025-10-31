from pydantic import BaseModel
from typing import Any,Optional

# TO DO: Need to add specific fields based on storage responses.For now, using generic Any type.

class StorageReadResponse(BaseModel):
    success: bool
    result: Optional[Any]
    error: Optional[str] = None

class StorageCreateFolderResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

class StorageGetFolderResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

class StorageUploadImageResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None