import httpx
from oserver.models.response_models import StorageUploadImageResponse
from oserver.utils.helpers import get_base_url


async def upload_image_to_storage(
    image_bytes: bytes,
    filename: str,
    folder_name: str,
    client_code: str,
    access_token: str
) -> StorageUploadImageResponse:
    
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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, files=files)
            response.raise_for_status()
            data = response.json()
            return StorageUploadImageResponse(success=True, result=data)
    except httpx.RequestError as e:
        return StorageUploadImageResponse(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return StorageUploadImageResponse(success=False, error=f"HTTP error: {str(e)}")
