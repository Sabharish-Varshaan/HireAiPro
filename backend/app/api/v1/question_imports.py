"""Company-private question import (docs/QUESTION_IMPORT.md). Every route resolves the caller's organization from the JOB (membership) or from the batch;
IDs inside an uploaded file are never trusted."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import get_job_for_member, member_org_ids
from app.core.database import get_db
from app.models.assessments import Assessment
from app.models.enums import UserRole
from app.models.organizations import Organization
from app.models.questions import QuestionImportBatch
from app.models.users import User
from app.services.audit import audit
from app.services.questions import company_import as ci

router = APIRouter(prefix="/question-imports", tags=["question-imports"])
RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)


async def _job_ctx(db: AsyncSession, user: User, job_id: uuid.UUID):
    job = await get_job_for_member(db, user, job_id)  # 404/403 unless the caller's company owns the job
    org = await db.get(Organization, job.organization_id)
    assessment = await db.scalar(select(Assessment).where(Assessment.job_id == job.id).order_by(Assessment.created_at.desc()))
    return job, org, assessment


async def _batch(db: AsyncSession, user: User, batch_id: uuid.UUID) -> QuestionImportBatch:
    b = await db.get(QuestionImportBatch, batch_id)
    if b is None or (user.role != UserRole.PLATFORM_ADMIN and b.organization_id not in await member_org_ids(db, user)):
        raise HTTPException(404, "Import not found")  # same answer for "does not exist" and "belongs to another company"
    return b


def _out(b: QuestionImportBatch, with_rows: bool = True) -> dict:
    d = {"id": b.id, "job_id": b.job_id, "assessment_id": b.assessment_id, "filename": b.filename, "format": b.format, "template_version": b.template_version,
         "status": b.status, "total_rows": b.total_rows, "valid_rows": b.valid_rows, "invalid_rows": b.invalid_rows, "duplicate_rows": b.duplicate_rows,
         "imported_rows": b.imported_rows, "created_at": b.created_at, "confirmed_at": b.confirmed_at}
    if with_rows:
        d["rows"] = b.rows
    return d


@router.get("/template")
async def template(job_id: uuid.UUID, format: str = "xlsx", user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    job, org, assessment = await _job_ctx(db, user, job_id)
    meta = ci.build_metadata(org=org, job=job, assessment=assessment)
    if format == "xlsx":
        body, mime, ext = ci.build_xlsx(meta), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif format == "csv":
        body, mime, ext = ci.build_csv(meta), "text/csv", "csv"
    elif format == "json":
        body, mime, ext = ci.build_json(meta), "application/json", "json"
    else:
        raise HTTPException(422, "format must be xlsx, csv or json")
    return Response(content=body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="questions-template.{ext}"'})


@router.post("")
async def upload(job_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    """Parse + validate into a PREVIEW batch. Nothing is a question yet."""
    job, org, assessment = await _job_ctx(db, user, job_id)
    try:
        rows, meta, fmt = ci.parse_upload(await file.read(ci.MAX_BYTES + 1), file.filename or "")
    except ci.ImportFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    if meta.get("company_id") and meta["company_id"] != str(org.id):  # metadata is a hint, never authority: a foreign template is refused outright
        raise HTTPException(422, "This template was generated for a different company. Download the template from your own job and try again.")
    results = [r.as_dict() for r in await ci.validate_rows(db, org.id, rows, assessment.id if assessment else None)]
    b = QuestionImportBatch(organization_id=org.id, job_id=job.id, assessment_id=assessment.id if assessment else None, uploaded_by=user.id,
                            filename=file.filename or "upload", format=fmt, template_version=meta.get("template_version"), status="PREVIEW", rows=results,
                            **ci.summarize(results))
    db.add(b)
    await audit(db, user, "question_import_uploaded", "question_import_batch", None, organization_id=org.id, metadata={"rows": len(results), "format": fmt})
    await db.commit()
    await db.refresh(b)
    return _out(b)


@router.get("/coverage")
async def coverage(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    job, org, assessment = await _job_ctx(db, user, job_id)
    return await ci.coverage_for_job(db, org.id, job, assessment)


@router.get("")
async def list_batches(job_id: uuid.UUID | None = None, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    orgs = await member_org_ids(db, user)
    stmt = select(QuestionImportBatch).where(QuestionImportBatch.organization_id.in_(orgs)).order_by(QuestionImportBatch.created_at.desc()).limit(50)
    if job_id:
        stmt = stmt.where(QuestionImportBatch.job_id == job_id)
    return [_out(b, with_rows=False) for b in (await db.scalars(stmt)).all()]


@router.get("/{batch_id}")
async def get_batch(batch_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    return _out(await _batch(db, user, batch_id))


class RowPatch(BaseModel):
    excluded: bool | None = None
    skill_id: uuid.UUID | None = None


@router.patch("/{batch_id}/rows/{row}")
async def patch_row(batch_id: uuid.UUID, row: int, payload: RowPatch, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    b = await _batch(db, user, batch_id)
    if b.status != "PREVIEW":
        raise HTTPException(409, "This import is already finished")
    idx = next((i for i, r in enumerate(b.rows) if r["row"] == row), None)
    if idx is None:
        raise HTTPException(404, "Row not found")
    if payload.skill_id is not None:
        from app.models.skills import Skill

        if await db.get(Skill, payload.skill_id) is None:
            raise HTTPException(422, "Unknown skill")
        await ci.revalidate_one(db, b.organization_id, b, idx, payload.skill_id)
    if payload.excluded is not None:
        b.rows = [*b.rows[:idx], {**b.rows[idx], "excluded": payload.excluded}, *b.rows[idx + 1:]]
    for k, v in ci.summarize(b.rows).items():
        setattr(b, k, v)
    await db.commit()
    await db.refresh(b)
    return _out(b)


@router.post("/{batch_id}/confirm")
async def confirm(batch_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    b = await _batch(db, user, batch_id)
    if b.status != "PREVIEW":
        raise HTTPException(409, "This import was already confirmed or cancelled")
    result = await ci.confirm_batch(db, b, user.id)
    await audit(db, user, "question_import_confirmed", "question_import_batch", b.id, organization_id=b.organization_id, metadata=result | {"question_ids": None})
    await db.commit()
    return {**result, "batch": _out(b, with_rows=False)}


@router.post("/{batch_id}/cancel")
async def cancel(batch_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    b = await _batch(db, user, batch_id)
    if b.status == "PREVIEW":
        b.status = "CANCELLED"
        await db.commit()
    return _out(b, with_rows=False)
