import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.enums import QuestionSourceType, QuestionStatus, UserRole, Visibility
from app.models.organizations import OrganizationMember
from app.models.questions import Question
from app.models.users import User
from app.schemas.questions import QuestionCreate, QuestionImportRow, QuestionOut
from app.services.skills.normalizer import normalize_skill_name

router = APIRouter(prefix="/questions", tags=["questions"])

RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)
ADMIN_ROLES = (UserRole.PLATFORM_ADMIN,)


async def _assert_org_member(db: AsyncSession, user: User, organization_id: uuid.UUID) -> None:
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == organization_id,
        )
    )
    if member is None:
        raise HTTPException(403, "Not a member of this organization")


@router.post("", response_model=QuestionOut)
async def create_question(
    payload: QuestionCreate,
    user: User = Depends(require_roles(*RECRUITER_ROLES, *ADMIN_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    if payload.organization_id:
        await _assert_org_member(db, user, payload.organization_id)
        source_type = QuestionSourceType.COMPANY_PRIVATE
        visibility = Visibility.COMPANY_PRIVATE
    else:
        source_type = QuestionSourceType.PLATFORM
        visibility = Visibility.PLATFORM_PUBLIC

    q = Question(
        question_bank_id=payload.question_bank_id,
        question_text=payload.question_text,
        question_type=payload.question_type,
        skill_id=payload.skill_id,
        difficulty=payload.difficulty,
        options=payload.options,
        correct_option_index=payload.correct_option_index,
        expected_concepts=payload.expected_concepts,
        rubric=payload.rubric,
        starter_code=payload.starter_code,
        test_cases=payload.test_cases,
        source_type=source_type,
        organization_id=payload.organization_id,
        visibility=visibility,
        status=QuestionStatus.DRAFT,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


@router.get("", response_model=list[QuestionOut])
async def list_questions(
    organization_id: uuid.UUID | None = None,
    skill_id: uuid.UUID | None = None,
    status: QuestionStatus | None = None,
    user: User = Depends(require_roles(*RECRUITER_ROLES, *ADMIN_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Recruiter view: platform questions + only their own org's private questions."""
    stmt = select(Question)
    if organization_id:
        await _assert_org_member(db, user, organization_id)
        stmt = stmt.where(
            or_(
                Question.visibility == Visibility.PLATFORM_PUBLIC,
                Question.organization_id == organization_id,
            )
        )
    else:
        stmt = stmt.where(Question.visibility == Visibility.PLATFORM_PUBLIC)
    if skill_id:
        stmt = stmt.where(Question.skill_id == skill_id)
    if status:
        stmt = stmt.where(Question.status == status)
    return (await db.scalars(stmt)).all()


@router.post("/{question_id}/approve", response_model=QuestionOut)
async def approve_question(
    question_id: uuid.UUID,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    q.status = QuestionStatus.APPROVED
    if q.source_type == QuestionSourceType.AI_GENERATED:
        q.visibility = Visibility.PLATFORM_PUBLIC
    await db.commit()
    await db.refresh(q)
    return q


@router.post("/{question_id}/reject", response_model=QuestionOut)
async def reject_question(
    question_id: uuid.UUID,
    user: User = Depends(require_roles(*ADMIN_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    q.status = QuestionStatus.REJECTED
    await db.commit()
    await db.refresh(q)
    return q


@router.post("/{question_id}/retire", response_model=QuestionOut)
async def retire_question(
    question_id: uuid.UUID,
    user: User = Depends(require_roles(*ADMIN_ROLES, *RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    q.status = QuestionStatus.RETIRED
    await db.commit()
    await db.refresh(q)
    return q


@router.post("/import", response_model=list[QuestionOut])
async def import_questions(
    rows: list[QuestionImportRow],
    organization_id: uuid.UUID,
    user: User = Depends(require_roles(*RECRUITER_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    await _assert_org_member(db, user, organization_id)
    created = []
    for row in rows:
        skill_id, _confidence = await normalize_skill_name(db, row.skill_name)
        if skill_id is None:
            continue
        q = Question(
            question_text=row.question_text,
            question_type=row.question_type,
            skill_id=skill_id,
            difficulty=row.difficulty,
            options=row.options,
            correct_option_index=row.correct_option_index,
            expected_concepts=row.expected_concepts,
            source_type=QuestionSourceType.COMPANY_PRIVATE,
            organization_id=organization_id,
            visibility=Visibility.COMPANY_PRIVATE,
            status=QuestionStatus.VALIDATED,
        )
        db.add(q)
        created.append(q)
    await db.commit()
    for q in created:
        await db.refresh(q)
    return created
