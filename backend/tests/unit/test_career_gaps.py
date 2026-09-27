import pytest

from app.models.enums import EvidenceSourceType as E
from app.services.career.gaps import calculate_skill_gaps, get_prerequisites
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence
from tests.factories import make_company, make_job, make_student, skill


@pytest.mark.asyncio
async def test_gap_is_required_minus_current_and_ordered(db):
    org, rec, _ = await make_company(db)
    job = await make_job(db, org, rec, [("Python", "required", 0.8, 1.0), ("Docker", "required", 0.6, 0.5), ("Git", "preferred", 0.3, 0.3)])
    st, _, _ = await make_student(db)
    await record_evidence(db, st.id, (await skill(db, "Python")).id, E.MCQ, 0.5, idempotency_key=f"p{st.id}")
    await record_evidence(db, st.id, (await skill(db, "Git")).id, E.MCQ, 0.9, idempotency_key=f"g{st.id}")
    await db.commit()
    await recalculate_all_skills_for_student(db, st.id)
    gaps = await calculate_skill_gaps(db, st.id, job.id)
    by = {g["skill_name"]: g for g in gaps}
    assert set(by) == {"Python", "Docker"}  # Git already meets its bar
    assert by["Python"]["gap"] == pytest.approx(0.3)
    assert by["Docker"]["gap"] == pytest.approx(0.6)
    assert [g["skill_name"] for g in gaps] == ["Python", "Docker"]  # 0.3*1.0 > 0.6*0.5


@pytest.mark.asyncio
async def test_prerequisite_graph(db):
    names = {p.canonical_name for p in await get_prerequisites(db, (await skill(db, "Kubernetes")).id)}
    assert "Docker" in names
