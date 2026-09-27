import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.documents import Document
from app.models.enums import JobStatus, UserRole, Visibility
from app.models.jobs import Job, JobSkill
from app.models.organizations import OrganizationMember
from app.models.misc import AuditEvent
from app.models.users import User
from app.schemas.jobs import ConfirmRequirementsRequest, JobCreate, JobOut, JobWithSkillsOut
from app.services.documents.extraction import extract_text
from app.services.storage.service import get_storage_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


async def _member_org_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    rows = (
        await db.scalars(
            select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id)
        )
    ).all()
    return list(rows)


@router.post("", response_model=JobOut)
async def create_job(
    payload: JobCreate,
    organization_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    org_ids = await _member_org_ids(db, user)
    if organization_id not in org_ids:
        raise HTTPException(403, "Not a member of this organization")
    job = Job(
        organization_id=organization_id,
        created_by_user_id=user.id,
        title=payload.title,
        description_raw=payload.description_raw,
        location=payload.location,
        employment_type=payload.employment_type,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/jd-file", response_model=JobOut)
async def upload_jd_file(
    job_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    content = await file.read()
    text = extract_text(content, file.content_type or "", file.filename or "")
    storage_key, sha256, size = get_storage_service().save(file.filename, content)
    doc = Document(
        owner_user_id=user.id,
        storage_key=storage_key,
        filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=sha256,
        visibility=Visibility.COMPANY_PRIVATE,
        doc_type="JD",
    )
    db.add(doc)
    await db.flush()
    job.jd_document_id = doc.id
    job.description_raw = text
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/process", status_code=202)
async def trigger_jd_processing(
    job_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if not job.description_raw:
        raise HTTPException(400, "Job has no JD text to process")
    from app.workers.tasks_jobs import process_jd_task

    process_jd_task.delay(str(job.id))
    return {"status": "queued"}


@router.get("/{job_id}", response_model=JobWithSkillsOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    skills = (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all()
    out = JobWithSkillsOut.model_validate(job)
    out.skills = skills
    return out


@router.get("", response_model=list[JobOut])
async def list_jobs(
    organization_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job)
    if organization_id:
        stmt = stmt.where(Job.organization_id == organization_id)
    if status:
        stmt = stmt.where(Job.status == status)
    return (await db.scalars(stmt.order_by(Job.created_at.desc()))).all()


@router.put("/{job_id}/requirements/confirm", response_model=JobWithSkillsOut)
async def confirm_requirements(
    job_id: uuid.UUID,
    payload: ConfirmRequirementsRequest,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Recruiter reviews/edits AI-suggested skills, then finalizes them.

    This is the mandatory human gate: assessment generation and matching may
    not run against unconfirmed job skills.
    """
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    existing = {
        s.id: s for s in (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all()
    }

    for item in payload.skills:
        if item.id and item.id in existing:
            row = existing[item.id]
            if item.delete:
                await db.delete(row)
                continue
            row.skill_id = item.skill_id
            row.raw_skill_name = item.raw_skill_name
            row.requirement_type = item.requirement_type
            row.minimum_level = item.minimum_level
            row.importance = item.importance
            row.confirmed = True
        elif not item.delete:
            db.add(
                JobSkill(
                    job_id=job.id,
                    skill_id=item.skill_id,
                    raw_skill_name=item.raw_skill_name,
                    requirement_type=item.requirement_type,
                    minimum_level=item.minimum_level,
                    importance=item.importance,
                    extraction_confidence=1.0,
                    confirmed=True,
                )
            )

    job.status = JobStatus.REQUIREMENTS_CONFIRMED
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="job_requirements_confirmed",
            entity_type="job",
            entity_id=job.id,
            event_metadata={"skill_count": len(payload.skills)},
        )
    )
    await db.commit()

    skills = (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all()
    out = JobWithSkillsOut.model_validate(job)
    out.skills = skills
    return out
