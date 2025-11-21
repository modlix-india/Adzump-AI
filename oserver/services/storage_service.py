import httpx
from oserver.utils.helpers import get_base_url
from oserver.models.storage_request_model import StorageReadRequest, StorageRequest, StorageRequestWithPayload,StorageUpdateRequest
from oserver.models.storage_response_model import StorageResponse


async def read_storage(request: StorageRequest, access_token: str, client_code: str):
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
            return StorageResponse(
                success=True,
                result=response_json,
                error=None
            )
    except httpx.RequestError as e:
        return StorageResponse(
            success=False,
            result=None,
            error=str(e)
        )

async def write_storage(request: StorageRequestWithPayload, access_token: str, client_code: str):
    base = get_base_url()
    url = f"{base}/api/core/function/execute/CoreServices.Storage/Create"
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
            return StorageResponse(
                success=True,
                result=response_json,
                error=None
            )
    except httpx.RequestError as e:
        return StorageResponse(
            success=False,
            result=None,
            error=str(e)
        )

async def read_storage_page(request: StorageReadRequest, access_token: str, client_code: str):
    base = get_base_url()
    url = f"{base}/api/core/function/execute/CoreServices.Storage/ReadPage"
    headers = {
        "authorization": access_token,
        "content-type": "application/json",
        "clientCode": client_code
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=request.model_dump())
            response.raise_for_status()
            response_json = response.json()
            return StorageResponse(
                success=True,
                result=response_json,
                error=None
            )
    except httpx.RequestError as e:
        return StorageResponse(
            success=False,
            result=None,
            error=str(e)
        )

async def update_storage_page(request: StorageUpdateRequest, access_token: str, client_code: str):
    base = get_base_url()
    url = f"{base}/api/core/function/execute/CoreServices.Storage/Update"
    headers = {
        "authorization": access_token,
        "content-type": "application/json",
        "clientCode": client_code
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=request.model_dump())
            response.raise_for_status()
            response_json = response.json()
            return StorageResponse(
                success=True,
                result=response_json,
                error=None
            )
    except httpx.RequestError as e:
        return StorageResponse(
            success=False,
            result=None,
            error=str(e)
        )