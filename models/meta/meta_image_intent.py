from pydantic import BaseModel


class MetaImageIntent(BaseModel):
    scene_type: str
    environment: str
    main_subject: str
    mood: str
    style: str
