from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

class RAGCollection(BaseModel):
    id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None

class RAGDocument(BaseModel):
    id: Optional[UUID] = None
    collection_id: UUID
    external_id: Optional[str] = None
    uri: Optional[str] = None
    source: str
    sha256: Optional[str] = None
    created_at: Optional[datetime] = None

class RAGChunk(BaseModel):
    id: Optional[UUID] = None
    document_id: UUID
    ord: int
    content: str
    metadata: Dict[str, Any] = {}
    tokens: Optional[int] = None
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None