import uuid

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    doc_type: str

    class Config:
        from_attributes = True
