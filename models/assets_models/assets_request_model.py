from pydantic import BaseModel

class AssetRequest(BaseModel):
    data_object_id: str
    asset_type: str
