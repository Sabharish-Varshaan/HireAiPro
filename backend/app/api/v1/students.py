import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.documents import Document
from app.models.enums import UserRole, Visibility
from app.models.students import (
    StudentCertification,
    StudentEducation,
    StudentExperience,
    StudentProfile,
    StudentProject,
)
from app.models.users import User
from app.schemas.students import (
    CertificationCreate,
    EducationCreate,
    ExperienceCreate,
    ProjectCreate,
    StudentProfileOut,
    StudentProfileUpdate,
)
from app.services.storage.service import get_storage_service

router = APIRouter(prefix="/students", tags=["students"])


async def _get_or_create_profile(db: AsyncSession, user: User) -> StudentProfile:
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        profile = StudentProfile(user_id=user.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


@router.get("/me", response_model=StudentProfileOut)
async def get_my_profile(
    user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)
):
    return await _get_or_create_profile(db, user)


@router.put("/me", response_model=StudentProfileOut)
async def update_my_profile(
    payload: StudentProfileUpdate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.get("/{student_id}", response_model=StudentProfileOut)
async def get_student_profile(student_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.api.tenancy import assert_can_view_student

    await assert_can_view_student(db, user, student_id)
    profile = await db.get(StudentProfile, student_id)
    if profile is None:
        raise HTTPException(404, "Student profile not found")
    return profile


@router.post("/me/education")
async def add_education(
    payload: EducationCreate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    row = StudentEducation(student_id=profile.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.post("/me/experience")
async def add_experience(
    payload: ExperienceCreate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    row = StudentExperience(student_id=profile.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.post("/me/projects")
async def add_project(
    payload: ProjectCreate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    row = StudentProject(student_id=profile.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.post("/me/certifications")
async def add_certification(
    payload: CertificationCreate,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    row = StudentCertification(student_id=profile.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.post("/me/resume")
async def upload_resume(
    file: UploadFile,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_or_create_profile(db, user)
    content = await file.read()
    name = (file.filename or "").lower()
    if not name.endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(415, "Upload a PDF, DOCX or TXT resume")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Resume must be under 10MB")
    storage_key, sha256, size = get_storage_service().save(file.filename, content)
    doc = Document(
        owner_user_id=user.id,
        storage_key=storage_key,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=sha256,
        visibility=Visibility.COMPANY_PRIVATE,
        doc_type="RESUME",
    )
    db.add(doc)
    await db.flush()
    profile.resume_document_id = doc.id
    profile.resume_parse_status = "PENDING"
    await db.commit()

    from app.workers.jobs import upsert_job
    from app.workers.tasks_resumes import process_resume_task

    await upsert_job(f"resume:{doc.id}", "resume_processing", {"student_id": str(profile.id), "document_id": str(doc.id)})
    process_resume_task.delay(str(profile.id), str(doc.id))
    return {"status": "queued", "document_id": doc.id}
