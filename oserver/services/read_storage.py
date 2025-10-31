import httpx
from oserver.utils.helpers import get_base_url
from oserver.models.request_models import StorageReadRequest
from oserver.models.response_models import StorageReadResponse


async def read_storage(request: StorageReadRequest, access_token: str, client_code: str):
    base = get_base_url()
    url = f"{base}/api/core/function/execute/CoreServices.Storage/Read"

    headers = {
        "authorization": access_token,
        "content-type": "application/json",
        "clientCode": client_code
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=headers, json=request.model_dump())
            response.raise_for_status()
            response_json = response.json()
            return StorageReadResponse(
                success=True,
                result=response_json,
                error=None
            )

    except httpx.RequestError as e:
        return StorageReadResponse(
            success=False,
            result=None,
            error=str(e)
        )
