import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import get_job_for_member, member_org_ids, require_org_member
from app.core.database import get_db
from app.models.documents import Document
from app.models.enums import JobStatus, UserRole, Visibility
from app.models.institutions import Institution
from app.models.jobs import Job, JobSkill
from app.models.misc import ProcessingJob
from app.models.organizations import Organization
from app.models.skills import Skill
from app.models.users import User
from app.schemas.jobs import ConfirmRequirementsRequest, JobCreate, JobOut, JobSkillOut, JobWithSkillsOut
from app.services.audit import audit
from app.services.documents.extraction import extract_text
from app.services.storage.service import get_storage_service
from app.services.jobs.visibility import student_can_access_job
from app.workers.jobs import upsert_job

router = APIRouter(prefix="/jobs", tags=["jobs"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)
VISIBLE_TO_STUDENTS = (JobStatus.PUBLISHED,)


class JDText(BaseModel):
    description_raw: str


async def _with_skills(db: AsyncSession, job: Job) -> JobWithSkillsOut:
    rows = (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id).order_by(JobSkill.importance.desc()))).all()
    out = JobWithSkillsOut.model_validate(job)
    names = {s.id: s.canonical_name for s in (await db.scalars(select(Skill).where(Skill.id.in_([r.skill_id for r in rows if r.skill_id])))).all()}
    out.skills = [JobSkillOut.model_validate(r).model_copy(update={"canonical_name": names.get(r.skill_id)}) for r in rows]
    org = await db.get(Organization, job.organization_id)
    out.organization_name = org.name if org else None
    if job.target_institution_id:
        inst = await db.get(Institution, job.target_institution_id)
        out.target_institution_name = inst.name if inst else None
    return out


@router.post("", response_model=JobOut)
async def create_job(
    payload: JobCreate,
    organization_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    await require_org_member(db, user, organization_id)
    job = Job(
        organization_id=organization_id, created_by_user_id=user.id, title=payload.title,
        description_raw=payload.description_raw, location=payload.location,
        employment_type=payload.employment_type, status=JobStatus.DRAFT,
    )
    db.add(job)
    await db.flush()
    await audit(db, user, "job_created", "job", job.id, organization_id=organization_id, metadata={"title": job.title})
    await db.commit()
    await db.refresh(job)
    return job


@router.put("/{job_id}/jd", response_model=JobOut)
async def set_jd_text(
    job_id: uuid.UUID, payload: JDText,
    user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db),
):
    job = await get_job_for_member(db, user, job_id)
    if JobStatus(job.status) not in (JobStatus.DRAFT, JobStatus.SKILLS_EXTRACTED):
        raise HTTPException(409, "Requirements are already confirmed; create a new job to change the JD")
    job.description_raw = payload.description_raw
    await audit(db, user, "job_description_changed", "job", job.id, organization_id=job.organization_id,
                metadata={"chars": len(payload.description_raw)})
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/jd-file", response_model=JobOut)
async def upload_jd_file(
    job_id: uuid.UUID, file: UploadFile,
    user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db),
):
    job = await get_job_for_member(db, user, job_id)
    content = await file.read()
    text = extract_text(content, file.content_type or "", file.filename or "")
    if not text.strip():
        raise HTTPException(422, "No text could be extracted from that file (PDF, DOCX or TXT expected)")
    storage_key, sha256, size = get_storage_service().save(file.filename, content)
    doc = Document(
        owner_user_id=user.id, storage_key=storage_key, filename=file.filename,
        mime_type=file.content_type or "application/octet-stream", size_bytes=size, sha256=sha256,
        visibility=Visibility.COMPANY_PRIVATE, doc_type="JD",
    )
    db.add(doc)
    await db.flush()
    job.jd_document_id = doc.id
    job.description_raw = text
    await audit(db, user, "job_description_uploaded", "job", job.id, organization_id=job.organization_id,
                metadata={"document_id": str(doc.id)})
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/process", status_code=202)
async def trigger_jd_processing(
    job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)
):
    job = await get_job_for_member(db, user, job_id)
    if not (job.description_raw or "").strip():
        raise HTTPException(400, "Job has no JD text to process")
    if JobStatus(job.status) not in (JobStatus.DRAFT, JobStatus.SKILLS_EXTRACTED):
        raise HTTPException(409, "Requirements are already confirmed")
    from app.workers.tasks_jobs import process_jd_task

    await upsert_job(f"jd:{job.id}", "jd_processing", {"job_id": str(job.id)})
    process_jd_task.delay(str(job.id))
    return {"status": "PROCESSING", "job_key": f"jd:{job.id}"}


@router.get("/{job_id}/processing")
async def jd_processing_status(
    job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await get_job_for_member(db, user, job_id)
    out = {}
    for key in (f"jd:{job_id}", f"assessment:{job_id}", f"matching:{job_id}"):
        pj = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_key == key))
        out[key.split(":")[0]] = (
            {"status": pj.status, "attempts": pj.attempts, "error": (pj.error or "").split("\n")[0] or None,
             "updated_at": pj.updated_at} if pj else None
        )
    return out


@router.get("/{job_id}", response_model=JobWithSkillsOut)
async def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if user.role == UserRole.STUDENT or job.organization_id not in await member_org_ids(db, user):
        if user.role == UserRole.STUDENT:
            if not await student_can_access_job(db, user, job):
                raise HTTPException(404, "Job not found")
        elif user.role != UserRole.PLATFORM_ADMIN and JobStatus(job.status) not in VISIBLE_TO_STUDENTS:
            raise HTTPException(404, "Job not found")
    return await _with_skills(db, job)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    organization_id: uuid.UUID | None = None,
    status: JobStatus | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job, Organization.name).join(Organization, Organization.id == Job.organization_id)
    if organization_id:
        await require_org_member(db, user, organization_id)
        stmt = stmt.where(Job.organization_id == organization_id)
        if status:
            stmt = stmt.where(Job.status == status)
    elif user.role == UserRole.PLATFORM_ADMIN:
        if status:
            stmt = stmt.where(Job.status == status)
    else:
        stmt = stmt.where(Job.status.in_([s.value for s in VISIBLE_TO_STUDENTS]))
    rows = (await db.execute(stmt.order_by(Job.created_at.desc()))).all()
    if not organization_id and user.role == UserRole.STUDENT:
        rows = [(j, n) for j, n in rows if await student_can_access_job(db, user, j)]
    elif not organization_id and user.role != UserRole.PLATFORM_ADMIN:
        rows = [(j, n) for j, n in rows if j.distribution_type != "INSTITUTION"]  # unapproved campus jobs stay private to their owner
    out = []
    for job, org_name in rows:
        item = JobOut.model_validate(job)
        item.organization_name = org_name
        out.append(item)
    return out


@router.put("/{job_id}/requirements/confirm", response_model=JobWithSkillsOut)
async def confirm_requirements(
    job_id: uuid.UUID, payload: ConfirmRequirementsRequest,
    user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db),
):
    """The mandatory human gate: only recruiter-confirmed, canonical skills
    are ever used for assessment generation and matching."""
    job = await get_job_for_member(db, user, job_id)
    if JobStatus(job.status) not in (JobStatus.DRAFT, JobStatus.SKILLS_EXTRACTED, JobStatus.REQUIREMENTS_CONFIRMED):
        raise HTTPException(409, f"Job is {job.status}; requirements can no longer change")
    kept = [s for s in payload.skills if not s.delete]
    unmapped = [s.raw_skill_name for s in kept if s.skill_id is None]
    if unmapped:
        raise HTTPException(422, f"Map these to a canonical skill or delete them before confirming: {unmapped}")
    if not kept:
        raise HTTPException(422, "At least one requirement must be confirmed")
    if len({s.skill_id for s in kept}) != len(kept):
        raise HTTPException(422, "Each canonical skill may appear only once")
    for s in kept:
        if await db.get(Skill, s.skill_id) is None:
            raise HTTPException(422, f"Unknown skill id {s.skill_id}")

    existing = {s.id: s for s in (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all()}
    changes = {"added": 0, "edited": 0, "deleted": 0}
    touched: set[uuid.UUID] = set()
    for item in payload.skills:
        row = existing.get(item.id) if item.id else None
        if item.delete:
            if row:
                await db.delete(row)
                changes["deleted"] += 1
            continue
        if row is None:
            row = JobSkill(job_id=job.id, extraction_confidence=1.0, raw_skill_name=item.raw_skill_name)
            db.add(row)
            changes["added"] += 1
        elif (row.skill_id, str(row.requirement_type), row.minimum_level, row.importance) != (
            item.skill_id, item.requirement_type.value, item.minimum_level, item.importance
        ):
            changes["edited"] += 1
        row.skill_id = item.skill_id
        row.raw_skill_name = item.raw_skill_name
        row.requirement_type = item.requirement_type
        row.minimum_level = item.minimum_level
        row.importance = item.importance
        row.confirmed = True
        await db.flush()
        touched.add(row.id)
    for sid, row in existing.items():  # anything the recruiter didn't send back is dropped, not silently kept
        if sid not in touched and row in db:
            if not any(i.id == sid for i in payload.skills):
                await db.delete(row)
                changes["deleted"] += 1

    job.status = JobStatus.REQUIREMENTS_CONFIRMED
    if any(changes.values()):
        await audit(db, user, "job_requirements_changed", "job", job.id, organization_id=job.organization_id, metadata=changes)
    await audit(db, user, "job_requirements_confirmed", "job", job.id, organization_id=job.organization_id,
                metadata={"skill_count": len(kept)})
    await db.commit()
    await db.refresh(job)
    return await _with_skills(db, job)


class DistributionIn(BaseModel):
    distribution_type: str  # OPEN_MARKET | INSTITUTION
    institution_id: uuid.UUID | None = None


@router.put("/{job_id}/distribution", response_model=JobOut)
async def set_distribution(job_id: uuid.UUID, payload: DistributionIn, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                           db: AsyncSession = Depends(get_db)):
    """Open market, or a partner institution whose placement officer must approve the opportunity."""
    job = await get_job_for_member(db, user, job_id)
    if payload.distribution_type not in ("OPEN_MARKET", "INSTITUTION"):
        raise HTTPException(422, "distribution_type must be OPEN_MARKET or INSTITUTION")
    if job.institution_approval == "APPROVED":
        raise HTTPException(409, "This opportunity was already approved by the institution and can no longer be re-targeted")
    published = JobStatus(job.status) == JobStatus.PUBLISHED
    if payload.distribution_type == "INSTITUTION":
        if payload.institution_id is None or await db.get(Institution, payload.institution_id) is None:
            raise HTTPException(422, "Choose an institution")
        job.distribution_type, job.target_institution_id = "INSTITUTION", payload.institution_id
        job.institution_approval = "PENDING" if published else "NOT_REQUIRED"
    else:
        job.distribution_type, job.target_institution_id, job.institution_approval = "OPEN_MARKET", None, "NOT_REQUIRED"
    job.approval_note = job.eligibility = None
    await audit(db, user, "job_distribution_set", "job", job.id, organization_id=job.organization_id,
                metadata={"type": job.distribution_type, "institution_id": str(job.target_institution_id) if job.target_institution_id else None})
    await db.commit()
    await db.refresh(job)
    return JobOut.model_validate(job)
