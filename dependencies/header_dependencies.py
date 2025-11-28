from fastapi import Header
from models.business_model import CommonHeaders


async def get_common_headers(
    access_token: str = Header(..., alias="access-token"),
    client_code: str = Header(..., alias="clientCode"),
    x_forwarded_host: str = Header(None, alias="x-forwarded-host"),
    x_forwarded_port: str = Header(None, alias="x-forwarded-port"),
) -> CommonHeaders:
    return CommonHeaders(
        access_token=access_token,
        client_code=client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port,
    )
