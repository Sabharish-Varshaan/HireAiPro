import uuid

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    doc_type: str

    model_config = ConfigDict(from_attributes=True)
