from pydantic import BaseModel, Field
from typing import List

class StorageReadRequest(BaseModel):
    storageName: str = Field(..., description="Name of the storage to read from")
    appCode: str = Field(default="marketingai", description="App code in NCLC")
    dataObjectId: str
    eager: bool = False
    eagerFields: List[str] = []