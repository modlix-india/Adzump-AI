import httpx
from oserver.models.response_models import StorageGetFolderResponse
from oserver.utils.helpers import get_base_url


async def get_folder(folder_name: str, access_token: str, client_code: str) -> StorageGetFolderResponse:
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
            return StorageGetFolderResponse(success=True, result=response.json())
    except httpx.RequestError as e:
        return StorageGetFolderResponse(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return StorageGetFolderResponse(success=False, error=f"HTTP error: {str(e)}")
