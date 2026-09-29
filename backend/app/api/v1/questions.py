import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import member_org_ids, require_org_member
from app.core.database import get_db
from app.models.enums import QuestionSourceType, QuestionStatus as QS, QuestionType, UserRole, Visibility
from app.models.questions import Question
from app.models.skills import Skill
from app.models.users import User
from app.schemas.questions import QuestionOut
from app.services.ai_gateway.vector_store import TenantScope
from app.services.audit import audit
from app.services.questions import importer
from app.services.questions.governance import GovernanceError, promote_to_platform, transition
from app.services.questions.validator import index_question, validate_semantics, validate_structure

router = APIRouter(prefix="/questions", tags=["questions"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)
ADMIN = UserRole.PLATFORM_ADMIN


class ManualQuestion(importer.ImportRow):
    organization_id: uuid.UUID | None = None


class PasteRequest(BaseModel):
    text: str
    skill: str
    question_type: QuestionType = QuestionType.TECHNICAL
    organization_id: uuid.UUID | None = None


class TransitionRequest(BaseModel):
    status: QS
    reason: str | None = None


async def _resolve_owner(db, user: User, organization_id: uuid.UUID | None) -> tuple[uuid.UUID | None, bool]:
    """Recruiters always write into their own organization's private bank;
    only a platform admin without an organization writes platform questions."""
    if user.role == ADMIN and organization_id is None:
        return None, True
    if organization_id is None:
        orgs = await member_org_ids(db, user)
        if len(orgs) != 1:
            raise HTTPException(422, "organization_id is required")
        organization_id = next(iter(orgs))
    await require_org_member(db, user, organization_id)
    return organization_id, False


async def _finish_import(db, user, report: importer.ImportReport, organization_id, platform: bool, how: str) -> dict:
    for q in report.created:
        await audit(db, user, "question_uploaded", "question", q.id, organization_id=organization_id,
                    metadata={"via": how, "status": q.status.value if hasattr(q.status, "value") else q.status})
    await db.commit()
    return report.as_dict()


async def _visible(db, user: User, q: Question | None) -> Question:
    if q is None:
        raise HTTPException(404, "Question not found")
    if user.role == ADMIN or q.visibility == Visibility.PLATFORM_PUBLIC:
        return q
    if q.organization_id and q.organization_id in await member_org_ids(db, user):
        return q
    raise HTTPException(404, "Question not found")  # 404, not 403: don't confirm another tenant's ids exist


@router.post("")
async def create_question(
    payload: ManualQuestion, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db)
):
    org, platform = await _resolve_owner(db, user, payload.organization_id)
    report = await importer.import_rows(db, [payload.model_dump(exclude={"organization_id"})], organization_id=org,
                                        created_by=user.id, platform=platform, provenance="COMPANY_MANUAL")
    return await _finish_import(db, user, report, org, platform, "manual")


@router.post("/import")
async def import_json_rows(
    rows: list[dict], organization_id: uuid.UUID | None = None,
    user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db),
):
    org, platform = await _resolve_owner(db, user, organization_id)
    report = await importer.import_rows(db, rows, organization_id=org, created_by=user.id, platform=platform)
    return await _finish_import(db, user, report, org, platform, "json_body")


@router.post("/import/file")
async def import_file(
    file: UploadFile, organization_id: uuid.UUID | None = None,
    user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db),
):
    org, platform = await _resolve_owner(db, user, organization_id)
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        rows = importer.parse_csv(raw) if name.endswith(".csv") else importer.parse_json(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Could not parse {file.filename}: {exc}") from exc
    report = await importer.import_rows(db, rows, organization_id=org, created_by=user.id, platform=platform)
    return await _finish_import(db, user, report, org, platform, "csv" if name.endswith(".csv") else "json_file")


@router.post("/import/paste")
async def import_paste(
    payload: PasteRequest, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db)
):
    org, platform = await _resolve_owner(db, user, payload.organization_id)
    rows = importer.parse_paste(payload.text, payload.skill, payload.question_type)
    report = await importer.import_rows(db, rows, organization_id=org, created_by=user.id, platform=platform)
    return await _finish_import(db, user, report, org, platform, "paste")


@router.get("", response_model=list[QuestionOut])
async def list_questions(
    organization_id: uuid.UUID | None = None,
    skill_id: uuid.UUID | None = None,
    status: QS | None = None,
    source_type: QuestionSourceType | None = None,
    question_type: QuestionType | None = None,
    domain: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = 200,
    user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Question)
    if user.role != ADMIN:
        orgs = await member_org_ids(db, user)
        if organization_id:
            await require_org_member(db, user, organization_id)
            orgs = {organization_id}
        stmt = stmt.where(or_(Question.visibility == Visibility.PLATFORM_PUBLIC, Question.organization_id.in_(orgs)))
    elif organization_id:
        stmt = stmt.where(Question.organization_id == organization_id)
    for col, val in ((Question.skill_id, skill_id), (Question.status, status), (Question.source_type, source_type),
                     (Question.question_type, question_type)):
        if val is not None:
            stmt = stmt.where(col == (val.value if hasattr(val, "value") else val))
    if domain:
        stmt = stmt.where(Question.domain == domain.upper())
    if category:
        stmt = stmt.where(Question.category == category)
    if q:
        stmt = stmt.where(Question.question_text.ilike(f"%{q}%"))
    rows = (await db.scalars(stmt.order_by(Question.created_at.desc()).limit(limit))).all()
    names = {s.id: s.canonical_name for s in (await db.scalars(select(Skill).where(Skill.id.in_({r.skill_id for r in rows})))).all()}
    return [QuestionOut.model_validate(r).model_copy(update={"skill_name": names.get(r.skill_id)}) for r in rows]


@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
                       db: AsyncSession = Depends(get_db)):
    q = await _visible(db, user, await db.get(Question, question_id))
    skill = await db.get(Skill, q.skill_id) if q.skill_id else None
    return QuestionOut.model_validate(q).model_copy(update={"skill_name": skill.canonical_name if skill else None})


@router.post("/{question_id}/validate", response_model=QuestionOut)
async def revalidate(question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
                     db: AsyncSession = Depends(get_db)):
    q = await _visible(db, user, await db.get(Question, question_id))
    skill = await db.get(Skill, q.skill_id) if q.skill_id else None
    r = validate_structure(QuestionType(q.question_type), q.question_text, q.difficulty, q.expected_concepts, q.rubric,
                           q.options, q.correct_option_index, q.test_cases)
    if skill is not None:  # skill-less (aptitude / HR) questions have no skill to align with; structure and hash checks apply
        r = validate_semantics(r, q.question_text, skill.canonical_name, q.skill_id, TenantScope(organization_id=q.organization_id))
    if r.duplicate_of == str(q.id):  # a question is never a duplicate of itself
        r.duplicate_of, r.checks["not_duplicate"] = None, True
        r.reasons = [x for x in r.reasons if "near-duplicate" not in x]
        r.ok = all(r.checks.values())
    q.validation_report = r.report()
    if r.ok and QS(q.status) == QS.DRAFT:
        q.status = QS.VALIDATED
    await audit(db, user, "question_validated", "question", q.id, organization_id=q.organization_id,
                metadata={"ok": r.ok, "reasons": r.reasons[:5]})
    await db.commit()
    if q.skill_id is not None:
        index_question(q, r.embedding)
    return q


@router.post("/{question_id}/transition", response_model=QuestionOut)
async def change_status(question_id: uuid.UUID, payload: TransitionRequest,
                        user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db)):
    q = await _visible(db, user, await db.get(Question, question_id))
    try:
        await transition(db, user, q, payload.status, await member_org_ids(db, user), payload.reason)
    except GovernanceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    affected = []
    if QS(payload.status) == QS.REJECTED:
        from app.services.evidence.service import retire_evidence_for_question

        affected = await retire_evidence_for_question(db, q.id)
        if affected:
            await audit(db, user, "question_evidence_retired", "question", q.id, organization_id=q.organization_id,
                        metadata={"students": len(affected)})
    await db.commit()
    if affected:
        from app.services.evidence.estimator import recalculate_all_skills_for_student

        for student_id in affected:
            await recalculate_all_skills_for_student(db, student_id, user.id, "question_rejected")
    index_question(q)
    return q


async def _shortcut(question_id, target: QS, user, db, reason=None):
    return await change_status(question_id, TransitionRequest(status=target, reason=reason), user, db)


@router.post("/{question_id}/approve", response_model=QuestionOut)
async def approve_question(question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
                           db: AsyncSession = Depends(get_db)):
    return await _shortcut(question_id, QS.APPROVED, user, db)


@router.post("/{question_id}/activate", response_model=QuestionOut)
async def activate_question(question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
                            db: AsyncSession = Depends(get_db)):
    return await _shortcut(question_id, QS.ACTIVE, user, db)


@router.post("/{question_id}/reject", response_model=QuestionOut)
async def reject_question(question_id: uuid.UUID, reason: str | None = None,
                          user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)), db: AsyncSession = Depends(get_db)):
    return await _shortcut(question_id, QS.REJECTED, user, db, reason)


@router.post("/{question_id}/retire", response_model=QuestionOut)
async def retire_question(question_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, ADMIN)),
                          db: AsyncSession = Depends(get_db)):
    return await _shortcut(question_id, QS.RETIRED, user, db)


@router.post("/{question_id}/promote", response_model=QuestionOut)
async def promote(question_id: uuid.UUID, user: User = Depends(require_roles(ADMIN)), db: AsyncSession = Depends(get_db)):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    try:
        await promote_to_platform(db, user, q)
    except GovernanceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    await db.commit()
    index_question(q)
    return q
