"""Placement-officer student management: single invite, CSV preview/import, resend, disable/enable.

The officer never sets or sees a password. A new email produces a PENDING record plus a single-use
invitation; an existing STUDENT account with that email is linked to the institution instead of duplicated.
"""

import csv
import io
import re
import uuid

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import InstitutionStudent
from app.models.enums import UserRole
from app.models.institutions import Cohort, Department, Institution
from app.models.students import StudentProfile
from app.models.users import User
from app.services.accounts.service import create_invitation

MAX_ROWS = 1000
MAX_BYTES = 1_000_000
COLUMNS = ["student_id", "first_name", "last_name", "email", "department", "program", "cohort", "graduation_year"]
ALIASES = {"registration_id": "student_id", "student_code": "student_id", "id": "student_id", "firstname": "first_name",
           "lastname": "last_name", "e-mail": "email", "batch": "cohort", "year": "graduation_year"}


def _norm_header(h: str) -> str:
    k = re.sub(r"\s+", "_", h.strip().lower())
    return ALIASES.get(k, k)


def parse_csv(raw: bytes) -> tuple[list[dict], str | None]:
    if len(raw) > MAX_BYTES:
        return [], "File is larger than 1 MB"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], "File must be UTF-8 text"
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], "File is empty"
    heads = {h: _norm_header(h) for h in reader.fieldnames if h}
    if "email" not in heads.values():
        return [], "Missing required column: email"
    rows = []
    for i, r in enumerate(reader, start=2):  # line 1 is the header
        rows.append({"line": i, **{heads[k]: (v or "").strip() for k, v in r.items() if k in heads}})
        if len(rows) > MAX_ROWS:
            return [], f"Too many rows (max {MAX_ROWS})"
    return rows, None


class Resolver:
    def __init__(self, departments: list[Department], cohorts: list[Cohort]):
        self.dep = {d.name.strip().lower(): d for d in departments}
        self.coh = {c.name.strip().lower(): c for c in cohorts}


async def resolver_for(db: AsyncSession, institution_id: uuid.UUID) -> Resolver:
    deps = (await db.scalars(select(Department).where(Department.institution_id == institution_id))).all()
    cohs = (await db.scalars(select(Cohort).where(Cohort.institution_id == institution_id))).all()
    return Resolver(list(deps), list(cohs))


async def validate_row(db: AsyncSession, institution_id: uuid.UUID, row: dict, res: Resolver, seen: set[str]) -> dict:
    """Returns {line, email, action: INVITE|LINK_EXISTING_ACCOUNT|ERROR, error?, fields}."""
    out = {"line": row.get("line"), "email": (row.get("email") or "").lower(), "action": "ERROR", "error": None, "fields": {}}
    try:
        email = validate_email(row.get("email", ""), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        out["error"] = "Invalid or missing email address"
        return out
    out["email"] = email
    if email in seen:
        out["error"] = "Duplicate email in this file"
        return out
    seen.add(email)
    fields: dict = {"student_code": row.get("student_id") or None, "first_name": row.get("first_name") or None,
                    "last_name": row.get("last_name") or None, "program": row.get("program") or None}
    dept = cohort = None
    if row.get("department"):
        dept = res.dep.get(row["department"].lower())
        if dept is None:
            out["error"] = f"Unknown department '{row['department']}' (create it under Academic Structure first)"
            return out
    if row.get("cohort"):
        cohort = res.coh.get(row["cohort"].lower())
        if cohort is None:
            out["error"] = f"Unknown cohort '{row['cohort']}' (create it under Academic Structure first)"
            return out
        if dept is None and cohort.department_id:
            dept = next((d for d in res.dep.values() if d.id == cohort.department_id), None)
        if dept is not None and cohort.department_id and cohort.department_id != dept.id:
            out["error"] = "Cohort does not belong to the given department"
            return out
    grad = None
    if row.get("graduation_year"):
        if not row["graduation_year"].isdigit() or not 1990 <= int(row["graduation_year"]) <= 2100:
            out["error"] = "graduation_year must be a 4-digit year"
            return out
        grad = int(row["graduation_year"])
    elif cohort is not None:
        grad = cohort.graduation_year
    fields.update(department_id=dept.id if dept else None, cohort_id=cohort.id if cohort else None, graduation_year=grad)
    out["fields"] = fields
    existing = await db.scalar(select(InstitutionStudent).where(InstitutionStudent.institution_id == institution_id,
                                                                InstitutionStudent.email == email))
    if existing:
        out["error"] = ("Already invited; use Resend Invite" if existing.status == "PENDING"
                        else "Already enrolled at this institution" if existing.status == "ACTIVE" else "Disabled; re-enable instead")
        return out
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        if user.role != UserRole.STUDENT.value:
            out["error"] = "This email belongs to a non-student account"
            return out
        profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        if profile and profile.institution_id and profile.institution_id != institution_id:
            out["error"] = "Student is already enrolled at another institution"
            return out
        out["action"] = "LINK_EXISTING_ACCOUNT"
        return out
    out["action"] = "INVITE"
    return out


async def apply_row(db: AsyncSession, institution: Institution, officer: User, v: dict) -> InstitutionStudent:
    """Persist one validated row (flush only; caller commits)."""
    f = v["fields"]
    rec = InstitutionStudent(institution_id=institution.id, email=v["email"], **f)
    db.add(rec)
    await db.flush()
    if v["action"] == "LINK_EXISTING_ACCOUNT":
        user = await db.scalar(select(User).where(User.email == v["email"]))
        profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        if profile is None:
            profile = StudentProfile(user_id=user.id)
            db.add(profile)
        profile.institution_id, profile.cohort_id = institution.id, f["cohort_id"]
        rec.user_id, rec.status = user.id, "ACTIVE"
    else:
        await invite(db, institution, officer, rec)
    return rec


async def invite(db: AsyncSession, institution: Institution, officer: User, rec: InstitutionStudent) -> None:
    name = " ".join(x for x in [rec.first_name, rec.last_name] if x) or "there"
    await create_invitation(db, email=rec.email, role=UserRole.STUDENT, created_by=officer.id, institution_id=institution.id,
                            institution_student_id=rec.id, subject=f"{institution.name} invited you to HireAiPro",
                            intro=f"Hello {name}, {institution.name} has set up your HireAiPro account for placements.")
