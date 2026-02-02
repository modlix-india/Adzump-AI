from pydantic import BaseModel
from typing import Optional


class MetaCreativeRequest(BaseModel):
    dataObjectId: str
    logoUrl: Optional[str] = None
