from typing import Optional
import httpx
from oserver.models.storage_response_model import StorageResponse
from oserver.utils.helpers import get_base_url


async def create_folder(folder_name: str, access_token: str, client_code: str, x_forwarded_host:Optional[str] = None,
    x_forwarded_port:Optional[str] = None) -> StorageResponse:
    base = get_base_url()
    url = f"{base}/api/files/secured/directory/{folder_name}"

    headers = {
        "accept": "application/json",
        "Authorization": access_token,
        "ClientCode": client_code,
        "AppCode": "marketingai",
        "X-Forwarded-Host": x_forwarded_host,
        "X-Forwarded-Port": x_forwarded_port
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            return StorageResponse(success=True, result=response.json())
    except httpx.RequestError as e:
        return StorageResponse(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return StorageResponse(success=False, error=f"HTTP error: {str(e)}")
    

async def get_folder(folder_name: str, access_token: str, client_code: str,x_forwarded_host:Optional[str] = None,
    x_forwarded_port:Optional[str] = None) -> StorageResponse:
    base = get_base_url()
    url = f"{base}/api/files/secured/{folder_name}"

    headers = {
        "accept": "application/json",
        "Authorization": access_token,
        "ClientCode": client_code,
        "AppCode": "marketingai",
        "X-Forwarded-Host": x_forwarded_host,
        "X-Forwarded-Port": x_forwarded_port
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return StorageResponse(success=True, result=response.json())
    except httpx.RequestError as e:
        return StorageResponse(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return StorageResponse(success=False, error=f"HTTP error: {str(e)}")
    

async def upload_file(
    image_bytes: bytes,
    filename: str,
    folder_name: str,
    client_code: str,
    access_token: str,
    x_forwarded_host:Optional[str] = None,
    x_forwarded_port:Optional[str] = None
) -> StorageResponse:
        
    base = get_base_url()
    url = f"{base}/api/files/secured/{folder_name}?clientCode={client_code}"
    headers = {
        "accept": "application/json",
        "Authorization": access_token,
        "ClientCode": client_code,
        "AppCode": "marketingai",
        "X-Forwarded-Host": x_forwarded_host,
        "X-Forwarded-Port": x_forwarded_port
    }
    files = {
        "file": (filename, image_bytes, "image/png"),
    }
    folder_ok = await ensure_folder(folder_name, access_token, client_code,x_forwarded_host=x_forwarded_host,
    x_forwarded_port=x_forwarded_port)
    if not folder_ok:
        raise Exception(f"Folder '{folder_name}' does not exist and could not be created")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, files=files)
            print("Upload response status code:", response)
            response.raise_for_status()
            data = response.json()
            print("Upload response data:", data)
            return StorageResponse(success=True, result=data)
    except httpx.RequestError as e:
        return StorageResponse(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return StorageResponse(success=False, error=f"HTTP error: {str(e)}")


async def ensure_folder(
    folder_name: str,
    access_token: str,
    client_code: str,
    x_forwarded_host: Optional[str] = None,
    x_forwarded_port: Optional[str] = None
) -> bool:
    folder_resp = await get_folder(
        folder_name,
        access_token,
        client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port
    )
    if folder_resp.success and folder_resp.result:
        return True

    create_resp = await create_folder(
        folder_name,
        access_token,
        client_code,
        x_forwarded_host=x_forwarded_host,
        x_forwarded_port=x_forwarded_port
    )
    return create_resp.success
