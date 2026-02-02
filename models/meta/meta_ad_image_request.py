from pydantic import BaseModel
from typing import Optional, Dict


class MetaAdImageRequest(BaseModel):
    dataObjectId: Optional[str] = None
    adAccountId: Optional[str] = None
    imagePreferences: Optional[Dict] = None
    imageUrl: Optional[str] = None
