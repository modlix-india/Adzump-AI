from oserver.models.response_models import StorageUploadImageResponse
from oserver.services.create_folder import create_folder
from oserver.services.get_folder import get_folder
from oserver.services.upload_image import upload_image_to_storage


class StorageManager:

    @staticmethod
    async def ensure_folder(folder_name: str, access_token: str, client_code: str) -> bool:
        folder_resp = await get_folder(folder_name, access_token, client_code)
        if folder_resp.success and folder_resp.result:
            return True

        create_resp = await create_folder(folder_name, access_token, client_code)
        return create_resp.success

    @staticmethod
    async def upload_screenshot(
        image_bytes: bytes,
        filename: str,
        folder_name: str,
        client_code: str,
        access_token: str
    ) -> StorageUploadImageResponse:
       
        folder_ok = await StorageManager.ensure_folder(folder_name, access_token, client_code)
        if not folder_ok:
            return StorageUploadImageResponse(
                success=False,
                error=f"Folder '{folder_name}' does not exist and could not be created"
            )

        upload_resp = await upload_image_to_storage(
            image_bytes=image_bytes,
            filename=filename,
            folder_name=folder_name,
            client_code=client_code,
            access_token=access_token
        )
        return upload_resp
