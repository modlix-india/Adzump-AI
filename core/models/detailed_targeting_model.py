from pydantic import BaseModel
from typing import List


class DetailedTargeting(BaseModel):
    interests: List[str] = []
    behaviors: List[str] = []
    demographics: List[str] = []
