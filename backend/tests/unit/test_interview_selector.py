import pytest

from app.models.enums import EvidenceSourceType as E
from app.models.interviews import Interview, InterviewTurn
from app.services.evidence.estimator import estimate_student_skill
from app.services.evidence.service import record_evidence
from app.services.interviews.selector import rank_candidates
from tests.factories import make_application, make_company, make_job, make_student, skill
from tests.fakes import rubric


async def _setup(db, skills):
    org, rec, _ = await make_company(db)
    job = await make_job(db, org, rec, skills)
    st, _, _ = await make_student(db)
    app_ = await make_application(db, job, st)
    iv = Interview(application_id=app_.id, student_id=st.id, job_id=job.id)
    db.add(iv)
    await db.flush()
    return job, st, iv


@pytest.mark.asyncio
async def test_high_confidence_python_is_deprioritized(db):
    job, st, iv = await _setup(db, [("Python", "required", 0.7, 1.0), ("Docker", "required", 0.5, 0.7), ("AWS", "required", 0.5, 0.6)])
    py = await skill(db, "Python")
    for t in (E.CODING, E.MCQ, E.INTERVIEW, E.TECHNICAL_ASSESSMENT):
        await record_evidence(db, st.id, py.id, t, 0.95, confidence=0.95, idempotency_key=f"{t}{st.id}")
    est = await estimate_student_skill(db, st.id, py.id)
    assert est.confidence >= 0.75
    ranked = await rank_candidates(db, job.id, st.id, iv.id)
    names = [c.skill_name for c in ranked]
    assert "Python" not in names
    assert names[0] == "Docker"  # higher importance than AWS, both zero evidence


@pytest.mark.asyncio
async def test_required_beats_preferred_at_equal_importance(db):
    job, st, iv = await _setup(db, [("Redis", "preferred", 0.5, 0.8), ("Docker", "required", 0.5, 0.8)])
    assert [c.skill_name for c in await rank_candidates(db, job.id, st.id, iv.id)] == ["Docker", "Redis"]


@pytest.mark.asyncio
async def test_skill_asked_twice_is_excluded_and_once_is_halved(db):
    job, st, iv = await _setup(db, [("Docker", "required", 0.5, 0.9), ("AWS", "required", 0.5, 0.5)])
    docker = await skill(db, "Docker")
    db.add(InterviewTurn(interview_id=iv.id, turn_index=0, target_skill_id=docker.id, question_text="q", difficulty="medium",
                         rubric_evaluation=rubric(0.6)))
    await db.flush()
    ranked = await rank_candidates(db, job.id, st.id, iv.id)
    assert ranked[0].skill_name == "AWS"  # 0.9*1.2*0.5=0.54 < 0.5*1.2=0.6
    db.add(InterviewTurn(interview_id=iv.id, turn_index=1, target_skill_id=docker.id, question_text="q2", difficulty="medium"))
    await db.flush()
    assert "Docker" not in [c.skill_name for c in await rank_candidates(db, job.id, st.id, iv.id)]


@pytest.mark.asyncio
async def test_strong_answer_raises_difficulty_weak_lowers_it(db):
    job, st, iv = await _setup(db, [("Docker", "required", 0.5, 0.9)])
    docker = await skill(db, "Docker")
    db.add(InterviewTurn(interview_id=iv.id, turn_index=0, target_skill_id=docker.id, question_text="q", difficulty="medium",
                         rubric_evaluation=rubric(0.9)))
    await db.flush()
    assert (await rank_candidates(db, job.id, st.id, iv.id))[0].difficulty == "hard"


@pytest.mark.asyncio
async def test_weak_answer_probes_prerequisite(db):
    job, st, iv = await _setup(db, [("FastAPI", "required", 0.7, 1.0), ("Docker", "required", 0.5, 0.5)])
    fa = await skill(db, "FastAPI")
    db.add(InterviewTurn(interview_id=iv.id, turn_index=0, target_skill_id=fa.id, question_text="q", difficulty="medium",
                         rubric_evaluation=rubric(0.1)))
    await db.flush()
    top = (await rank_candidates(db, job.id, st.id, iv.id))[0]
    assert top.skill_name in {"Pydantic", "Python", "REST APIs"}  # a real prerequisite of FastAPI in the graph
    assert top.difficulty == "easy"
