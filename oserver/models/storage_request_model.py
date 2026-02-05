from pydantic import BaseModel, Field
from typing import Any, List, Optional

class StorageRequest(BaseModel):
    storageName: str = Field(..., description="Name of the storage to read from")
    appCode: str = Field(default="marketingai", description="App code in NCLC")
    clientCode: str = Field(..., description="Client code for tenant identification")
    dataObjectId: str
    eager: bool = False
    eagerFields: List[str] = []

class StorageRequestWithPayload(BaseModel):
    storageName: str = Field(..., description="Name of the storage to create in")
    appCode: str = Field(default="marketingai", description="App code in NCLC")
    dataObject: Any
    eager: bool = False
    eagerFields: List[str] = []

class StorageUpdateWithPayload(BaseModel):
    storageName: str = Field(..., description="Name of the storage to create in")
    appCode: str = Field(default="marketingai", description="App code in NCLC")
    dataObject: Any
    dataObjectId: str
    isPartial: bool = Field(default=True, description="Whether to partially update the record")
    eager: bool = False
    eagerFields: List[str] = []

class StorageFilter(BaseModel):
    field: str = Field(..., description="Field name to filter records by")
    value: Any = Field(..., description="Value to match for the given field")

class StorageReadRequest(BaseModel):
    storageName: str = Field(..., description="Name of the storage to read from")
    appCode: str = Field(default="marketingai", description="App code in NCLC")
    clientCode: str = Field(..., description="Client code for tenant identification")
    eager: bool = Field(default=False, description="Whether to eagerly load related data")
    eagerFields: List[str] = Field(default_factory=list, description="List of fields to eagerly load")
    filter: Optional[StorageFilter] = Field(None, description="Optional filter condition for fetching specific records")
    size: Optional[int] = Field(None, description="Number of records per page")
