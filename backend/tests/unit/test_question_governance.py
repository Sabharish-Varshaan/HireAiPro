import pytest

from app.models.enums import QuestionSourceType as Src, QuestionStatus as QS, QuestionType, UserRole, Visibility
from app.models.questions import Question
from app.services.questions.governance import GovernanceError, can_transition, promote_to_platform, transition
from tests.factories import make_company, make_user, skill


def test_lifecycle_edges():
    assert can_transition(QS.DRAFT, QS.VALIDATED)
    assert can_transition(QS.VALIDATED, QS.APPROVED)
    assert can_transition(QS.APPROVED, QS.ACTIVE)
    assert can_transition(QS.ACTIVE, QS.RETIRED)
    assert can_transition(QS.VALIDATED, QS.REJECTED)
    assert not can_transition(QS.DRAFT, QS.ACTIVE)
    assert not can_transition(QS.RETIRED, QS.ACTIVE)
    assert not can_transition(QS.ACTIVE, QS.DRAFT)


async def _q(db, org, source=Src.AI_GENERATED, status=QS.VALIDATED, refs=None):
    q = Question(question_text="Explain how Docker layer caching works.", question_type=QuestionType.TECHNICAL,
                 skill_id=(await skill(db, "Docker")).id, difficulty="medium", source_type=source,
                 organization_id=org.id, visibility=Visibility.COMPANY_PRIVATE, status=status,
                 validation_report={"ok": True}, source_refs=refs or [])
    db.add(q)
    await db.flush()
    return q


@pytest.mark.asyncio
async def test_ai_question_never_becomes_global_without_platform_admin(db):
    org, rec, _ = await make_company(db)
    q = await _q(db, org)
    await transition(db, rec, q, QS.APPROVED, {org.id})
    assert q.visibility == Visibility.COMPANY_PRIVATE  # approval doesn't change visibility
    with pytest.raises(GovernanceError) as e:
        await promote_to_platform(db, rec, q)
    assert e.value.status_code == 403
    admin, _ = await make_user(db, UserRole.PLATFORM_ADMIN)
    await promote_to_platform(db, admin, q)
    assert q.visibility == Visibility.PLATFORM_PUBLIC and q.organization_id is None


@pytest.mark.asyncio
async def test_company_uploaded_questions_can_never_be_promoted(db):
    org, rec, _ = await make_company(db)
    admin, _ = await make_user(db, UserRole.PLATFORM_ADMIN)
    q = await _q(db, org, source=Src.COMPANY_PRIVATE, status=QS.APPROVED)
    with pytest.raises(GovernanceError):
        await promote_to_platform(db, admin, q)


@pytest.mark.asyncio
async def test_question_grounded_on_private_knowledge_cannot_be_promoted(db):
    org, _, _ = await make_company(db)
    admin, _ = await make_user(db, UserRole.PLATFORM_ADMIN)
    q = await _q(db, org, status=QS.APPROVED, refs=[{"document_id": "x", "chunk_id": "y", "visibility": "COMPANY_PRIVATE"}])
    with pytest.raises(GovernanceError):
        await promote_to_platform(db, admin, q)


@pytest.mark.asyncio
async def test_other_company_cannot_manage_question(db):
    org_a, _, _ = await make_company(db, "A")
    org_b, rec_b, _ = await make_company(db, "B")
    q = await _q(db, org_a)
    with pytest.raises(GovernanceError) as e:
        await transition(db, rec_b, q, QS.APPROVED, {org_b.id})
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_transition_rejected(db):
    org, rec, _ = await make_company(db)
    q = await _q(db, org, status=QS.DRAFT)
    with pytest.raises(GovernanceError):
        await transition(db, rec, q, QS.ACTIVE, {org.id})
