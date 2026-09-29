import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import member_institution_ids
from app.core.database import get_db
from app.models.accounts import InstitutionStudent, Invitation
from app.models.enums import UserRole
from app.models.institutions import Cohort, Department, Institution
from app.models.students import StudentProfile
from app.models.users import User
from app.services.audit import audit
from app.services.institutions import students as svc

router = APIRouter(prefix="/institutions", tags=["institution-students"])
OFFICER = (UserRole.PLACEMENT_OFFICER, UserRole.INSTITUTION_ADMIN)  # institution-admin kept working, deferred in UI


class InviteIn(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    student_id: str | None = None
    department: str | None = None
    program: str | None = None
    cohort: str | None = None
    graduation_year: str | None = None


async def _inst(db, user: User, institution_id: uuid.UUID) -> Institution:
    if institution_id not in await member_institution_ids(db, user):
        raise HTTPException(404, "Institution not found")
    return await db.get(Institution, institution_id)


async def _record(db, inst_id, sid) -> InstitutionStudent:
    r = await db.get(InstitutionStudent, sid)
    if r is None or r.institution_id != inst_id:
        raise HTTPException(404, "Student not found")
    return r


@router.get("/{institution_id}/student-records")
async def list_students(institution_id: uuid.UUID, status: str | None = None, user: User = Depends(require_roles(*OFFICER)),
                        db: AsyncSession = Depends(get_db)):
    await _inst(db, user, institution_id)
    stmt = (select(InstitutionStudent, Department.name, Cohort.name, User.full_name, StudentProfile.id)
            .outerjoin(Department, Department.id == InstitutionStudent.department_id)
            .outerjoin(Cohort, Cohort.id == InstitutionStudent.cohort_id)
            .outerjoin(User, User.id == InstitutionStudent.user_id)
            .outerjoin(StudentProfile, StudentProfile.user_id == InstitutionStudent.user_id)
            .where(InstitutionStudent.institution_id == institution_id).order_by(InstitutionStudent.created_at.desc()))
    if status:
        stmt = stmt.where(InstitutionStudent.status == status)
    counts = dict((await db.execute(select(InstitutionStudent.status, func.count()).where(
        InstitutionStudent.institution_id == institution_id).group_by(InstitutionStudent.status))).all())
    rows = [{"id": r.id, "email": r.email, "name": full or " ".join(x for x in [r.first_name, r.last_name] if x) or None,
             "student_code": r.student_code, "department": d, "program": r.program, "cohort": c,
             "graduation_year": r.graduation_year, "status": r.status, "student_profile_id": pid,
             "invited_at": r.created_at} for r, d, c, full, pid in (await db.execute(stmt)).all()]
    return {"counts": {"PENDING": counts.get("PENDING", 0), "ACTIVE": counts.get("ACTIVE", 0), "DISABLED": counts.get("DISABLED", 0)},
            "students": rows}


@router.post("/{institution_id}/student-records/invite")
async def invite_one(institution_id: uuid.UUID, payload: InviteIn, user: User = Depends(require_roles(*OFFICER)),
                     db: AsyncSession = Depends(get_db)):
    inst = await _inst(db, user, institution_id)
    res = await svc.resolver_for(db, institution_id)
    row = {"line": 1, **{k: (v or "") for k, v in payload.model_dump().items()}}
    v = await svc.validate_row(db, institution_id, row, res, set())
    if v["action"] == "ERROR":
        raise HTTPException(422, v["error"])
    rec = await svc.apply_row(db, inst, user, v)
    await audit(db, user, "student_invited" if v["action"] == "INVITE" else "student_linked", "institution_student", rec.id,
                metadata={"institution_id": str(institution_id)})
    await db.commit()
    return {"id": rec.id, "status": rec.status, "action": v["action"]}


async def _read_csv(file: UploadFile):
    rows, err = svc.parse_csv(await file.read(svc.MAX_BYTES + 1))
    if err:
        raise HTTPException(422, err)
    return rows


@router.post("/{institution_id}/student-records/import/preview")
async def import_preview(institution_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(require_roles(*OFFICER)),
                         db: AsyncSession = Depends(get_db)):
    await _inst(db, user, institution_id)
    rows = await _read_csv(file)
    res, seen = await svc.resolver_for(db, institution_id), set()
    results = [await svc.validate_row(db, institution_id, r, res, seen) for r in rows]
    for r in results:
        r.pop("fields")
    return {"total": len(results), "invite": sum(r["action"] == "INVITE" for r in results),
            "link_existing": sum(r["action"] == "LINK_EXISTING_ACCOUNT" for r in results),
            "errors": sum(r["action"] == "ERROR" for r in results), "rows": results}


@router.post("/{institution_id}/student-records/import/confirm")
async def import_confirm(institution_id: uuid.UUID, file: UploadFile = File(...), user: User = Depends(require_roles(*OFFICER)),
                         db: AsyncSession = Depends(get_db)):
    """Re-validates the uploaded file server-side (the preview is never trusted), imports the valid rows and
    reports every invalid row explicitly."""
    inst = await _inst(db, user, institution_id)
    rows = await _read_csv(file)
    res, seen, out = await svc.resolver_for(db, institution_id), set(), []
    for r in rows:
        v = await svc.validate_row(db, institution_id, r, res, seen)
        if v["action"] != "ERROR":
            await svc.apply_row(db, inst, user, v)
        v.pop("fields")
        out.append(v)
    await audit(db, user, "students_imported", "institution", institution_id,
                metadata={"rows": len(out), "errors": sum(r["action"] == "ERROR" for r in out)})
    await db.commit()
    return {"total": len(out), "invited": sum(r["action"] == "INVITE" for r in out),
            "linked": sum(r["action"] == "LINK_EXISTING_ACCOUNT" for r in out),
            "errors": sum(r["action"] == "ERROR" for r in out), "rows": out}


@router.post("/{institution_id}/student-records/{sid}/resend")
async def resend(institution_id: uuid.UUID, sid: uuid.UUID, user: User = Depends(require_roles(*OFFICER)),
                 db: AsyncSession = Depends(get_db)):
    inst = await _inst(db, user, institution_id)
    rec = await _record(db, institution_id, sid)
    if rec.status != "PENDING":
        raise HTTPException(409, "Only pending invitations can be resent")
    await svc.invite(db, inst, user, rec)
    await db.commit()
    return {"status": "resent"}


@router.post("/{institution_id}/student-records/{sid}/disable")
async def disable(institution_id: uuid.UUID, sid: uuid.UUID, user: User = Depends(require_roles(*OFFICER)),
                  db: AsyncSession = Depends(get_db)):
    """Ends the institution membership (roster, analytics, eligibility). The student's own account and password are untouched."""
    await _inst(db, user, institution_id)
    rec = await _record(db, institution_id, sid)
    if rec.status == "PENDING":  # kill any open link
        from datetime import datetime, timezone

        for inv in (await db.scalars(select(Invitation).where(Invitation.institution_student_id == rec.id,
                                                              Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None)))).all():
            inv.revoked_at = datetime.now(timezone.utc)
    if rec.user_id:
        p = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == rec.user_id))
        if p and p.institution_id == institution_id:
            p.institution_id = None
            p.cohort_id = None
    rec.status = "DISABLED"
    await audit(db, user, "student_disabled", "institution_student", rec.id)
    await db.commit()
    return {"status": rec.status}


@router.post("/{institution_id}/student-records/{sid}/enable")
async def enable(institution_id: uuid.UUID, sid: uuid.UUID, user: User = Depends(require_roles(*OFFICER)),
                 db: AsyncSession = Depends(get_db)):
    inst = await _inst(db, user, institution_id)
    rec = await _record(db, institution_id, sid)
    if rec.status != "DISABLED":
        raise HTTPException(409, "Student is not disabled")
    if rec.user_id:
        p = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == rec.user_id))
        if p and p.institution_id and p.institution_id != institution_id:
            raise HTTPException(409, "Student is enrolled at another institution")
        if p is None:
            p = StudentProfile(user_id=rec.user_id)
            db.add(p)
        p.institution_id, p.cohort_id = institution_id, rec.cohort_id
        rec.status = "ACTIVE"
    else:
        rec.status = "PENDING"
        await svc.invite(db, inst, user, rec)
    await db.commit()
    return {"status": rec.status}
