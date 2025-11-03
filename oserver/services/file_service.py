import httpx
from oserver.models.storage_response_model import StorageResponse
from oserver.utils.helpers import get_base_url


async def create_folder(folder_name: str, access_token: str, client_code: str) -> StorageResponse:
    base = get_base_url()
    url = f"{base}/api/files/secured/directory/{folder_name}"

    headers = {
        "accept": "application/json",
        "authorization": access_token,
        "clientcode": client_code,
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
    

async def get_folder(folder_name: str, access_token: str, client_code: str) -> StorageResponse:
    base = get_base_url()
    url = f"{base}/api/files/secured/{folder_name}"

    headers = {
        "accept": "application/json",
        "authorization": access_token,
        "clientcode": client_code,
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
    access_token: str
) -> StorageResponse:
    
    base = get_base_url()
    url = f"{base}/api/files/secured/{folder_name}?clientCode={client_code}"
    headers = {
        "accept": "application/json",
        "authorization": access_token,
        "clientcode": client_code,
    }
    files = {
        "file": (filename, image_bytes, "image/png"),
    }    
    folder_ok = await ensure_folder(folder_name, access_token, client_code)
    print("Folder check/create status:", folder_ok)
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


async def ensure_folder(folder_name: str, access_token: str, client_code: str) -> bool:
        folder_resp = await get_folder(folder_name, access_token, client_code)
        if folder_resp.success and folder_resp.result:
            return True

        create_resp = await create_folder(folder_name, access_token, client_code)
        return create_resp.success