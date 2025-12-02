from typing import Optional
from fastapi import Header
from openai import BaseModel

class CommonHeaders(BaseModel):
    access_token: str
    client_code: str
    x_forwarded_host: Optional[str] = None
    x_forwarded_port: Optional[str] = None


async def get_common_headers(
    access_token: str = Header(..., alias="access-token"),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: Optional[str] = Header(None, alias="x-forwarded-host"),
    x_forwarded_port: Optional[str] = Header(None, alias="x-forwarded-port"),
) -> CommonHeaders:
    return CommonHeaders(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )
