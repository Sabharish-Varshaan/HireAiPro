from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.documents import Document
from app.models.enums import Visibility
from app.models.users import User
from app.schemas.documents import DocumentOut
from app.services.storage.service import get_storage_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    doc_type: str = "GENERIC",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    storage_key, sha256, size = get_storage_service().save(file.filename, content)
    doc = Document(
        owner_user_id=user.id,
        storage_key=storage_key,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=sha256,
        visibility=Visibility.COMPANY_PRIVATE,
        doc_type=doc_type,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc
