from pydantic import BaseModel


class AgeTargeting(BaseModel):
    age_min: int | None = None
    age_max: int | None = None
    age_ranges: list[str] = []


class GenderTargeting(BaseModel):
    genders: list[str]
