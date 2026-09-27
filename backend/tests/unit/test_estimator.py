import pytest

from app.models.enums import EvidenceSourceType as E
from app.services.evidence.estimator import estimate_student_skill
from app.services.evidence.service import record_evidence
from tests.factories import make_student, skill


@pytest.mark.asyncio
async def test_resume_claim_alone_produces_no_skill_level(db):
    s, _, _ = await make_student(db)
    py = await skill(db, "Python")
    await record_evidence(db, s.id, py.id, E.RESUME_CLAIM, 0.99, confidence=0.99, idempotency_key="rc1" + str(s.id))
    assert await estimate_student_skill(db, s.id, py.id) is None


@pytest.mark.asyncio
async def test_resume_claim_does_not_move_level(db):
    s, _, _ = await make_student(db)
    py = await skill(db, "Python")
    await record_evidence(db, s.id, py.id, E.MCQ, 0.5, confidence=0.6, idempotency_key=f"m{s.id}")
    before = (await estimate_student_skill(db, s.id, py.id)).estimated_level
    await record_evidence(db, s.id, py.id, E.RESUME_CLAIM, 1.0, confidence=1.0, idempotency_key=f"r{s.id}")
    after = (await estimate_student_skill(db, s.id, py.id)).estimated_level
    assert before == after == 0.5


@pytest.mark.asyncio
async def test_weights_renormalize_over_present_types(db):
    s, _, _ = await make_student(db)
    sk = await skill(db, "Docker")
    await record_evidence(db, s.id, sk.id, E.CODING, 1.0, idempotency_key=f"c{s.id}")
    await record_evidence(db, s.id, sk.id, E.INTERVIEW, 0.4, idempotency_key=f"i{s.id}")
    est = await estimate_student_skill(db, s.id, sk.id)
    # coding 0.40 and interview 0.20 renormalize to 2/3 and 1/3
    assert est.estimated_level == pytest.approx(1.0 * 2 / 3 + 0.4 * 1 / 3)
    assert est.evidence_count == 2


@pytest.mark.asyncio
async def test_same_event_recorded_twice_is_one_row(db):
    s, _, _ = await make_student(db)
    sk = await skill(db, "Redis")
    a = await record_evidence(db, s.id, sk.id, E.MCQ, 1.0, source_id=s.id)
    b = await record_evidence(db, s.id, sk.id, E.MCQ, 0.0, source_id=s.id)
    assert a.id == b.id and b.normalized_score == 0.0
    assert (await estimate_student_skill(db, s.id, sk.id)).evidence_count == 1


@pytest.mark.asyncio
async def test_deleted_evidence_is_excluded(db):
    s, _, _ = await make_student(db)
    sk = await skill(db, "AWS")
    ev = await record_evidence(db, s.id, sk.id, E.MCQ, 1.0, idempotency_key=f"d{s.id}")
    ev.is_deleted = True
    await db.flush()
    assert await estimate_student_skill(db, s.id, sk.id) is None


@pytest.mark.asyncio
async def test_more_diverse_evidence_raises_confidence(db):
    s1, _, _ = await make_student(db)
    s2, _, _ = await make_student(db)
    sk = await skill(db, "Git")
    await record_evidence(db, s1.id, sk.id, E.MCQ, 0.8, confidence=0.6, idempotency_key=f"a{s1.id}")
    for t in (E.MCQ, E.CODING, E.INTERVIEW):
        await record_evidence(db, s2.id, sk.id, t, 0.8, confidence=0.6, idempotency_key=f"{t}{s2.id}")
    c1 = (await estimate_student_skill(db, s1.id, sk.id)).confidence
    c2 = (await estimate_student_skill(db, s2.id, sk.id)).confidence
    assert c2 > c1
