import pytest

from app.core.database import AsyncSessionLocal
from app.models.enums import EvidenceSourceType as E
from app.services.analytics.institution import strengths_and_gaps
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence
from tests.factories import make_company, make_institution, make_job, make_student, skill


@pytest.mark.asyncio
async def test_gaps_and_strengths_are_disjoint_by_sign():
    async with AsyncSessionLocal() as db:
        inst, _, _ = await make_institution(db)
        org, rec, _ = await make_company(db)
        await make_job(db, org, rec, [("Python", "required", 0.6, 1.0), ("AWS", "required", 0.6, 0.8)])
        st, _, _ = await make_student(db, institution=inst)
        py = await skill(db, "Python")
        for t in (E.CODING, E.TECHNICAL_ASSESSMENT, E.INTERVIEW):
            await record_evidence(db, st.id, py.id, t, 1.0, confidence=0.95, idempotency_key=f"an{t}{st.id}")
        await db.commit()
        await recalculate_all_skills_for_student(db, st.id)
        out = await strengths_and_gaps(db, inst.id, limit=50)

    assert out["students"] == 1
    assert all(r["gap"] > 0 for r in out["gaps"])  # a skill the cohort already exceeds is never a "gap"
    assert all(r["gap"] <= 0 for r in out["strengths"])
    assert "Python" not in {r["skill_name"] for r in out["gaps"]}
    assert "Python" in {r["skill_name"] for r in out["strengths"]}
    assert "AWS" in {r["skill_name"] for r in out["gaps"]}  # no evidence counts as 0


@pytest.mark.asyncio
async def test_placement_cards_respect_cohort_filter():
    from app.models.institutions import Cohort
    from app.services.analytics.institution import placement_readiness

    async with AsyncSessionLocal() as db:
        inst, _, _ = await make_institution(db)
        a, b = Cohort(institution_id=inst.id, name="A"), Cohort(institution_id=inst.id, name="B")
        db.add_all([a, b])
        await db.flush()
        await make_student(db, institution=inst, cohort=a)
        await db.commit()
        whole = await placement_readiness(db, inst.id)
        only_a = await placement_readiness(db, inst.id, cohort_id=a.id)
        only_b = await placement_readiness(db, inst.id, cohort_id=b.id)
    assert whole["total_students"] == only_a["total_students"] == 1
    assert only_b["total_students"] == 0
