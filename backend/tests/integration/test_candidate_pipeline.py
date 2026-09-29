"""Assessment → evidence → student skill → match, through the real API.
Judge0 runs for real; the rubric LLM is faked so scores are known."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.assessments import Assessment, AssessmentQuestion, AssessmentSection
from app.models.enums import EvidenceSourceType, QuestionSourceType, QuestionStatus, QuestionType, Visibility
from app.models.evidence import SkillEvidence
from app.models.misc import AuditEvent, Notification
from app.models.questions import Question
from tests.factories import make_company, make_job, make_student, skill
from tests.fakes import FakeLLM, rubric

SOLUTION = "import ast,sys\nnums=ast.literal_eval(sys.stdin.read())\nprint(sum(nums))\n"


async def _published_assessment(db, org, job):
    py, pg = await skill(db, "Python"), await skill(db, "PostgreSQL")
    qs = [
        Question(question_text="Which keyword defines a generator function's output in Python?", question_type=QuestionType.MCQ,
                 skill_id=py.id, options=["return", "yield", "emit"], correct_option_index=1),
        Question(question_text="Explain when a PostgreSQL B-tree index is used by the planner.", question_type=QuestionType.TECHNICAL,
                 skill_id=pg.id, expected_concepts=["selectivity", "range"], rubric={"criteria": ["selectivity", "range"]}),
        Question(question_text="Read a list of integers from stdin and print their sum.", question_type=QuestionType.CODING,
                 skill_id=py.id, starter_code="import ast,sys\n",
                 test_cases=[{"input": "[1, 2, 3]", "expected_output": "6"}, {"input": "[10, -4]", "expected_output": "6"},
                             {"input": "[0]", "expected_output": "0"}]),
    ]
    for q in qs:
        q.difficulty, q.source_type, q.organization_id = "medium", QuestionSourceType.COMPANY_PRIVATE, org.id
        q.visibility, q.status = Visibility.COMPANY_PRIVATE, QuestionStatus.APPROVED
        db.add(q)
    a = Assessment(job_id=job.id, title="t", status="PUBLISHED")
    db.add(a)
    await db.flush()
    sec = AssessmentSection(assessment_id=a.id, title="all", order_index=0)
    db.add(sec)
    await db.flush()
    aqs = []
    for i, q in enumerate(qs):
        aq = AssessmentQuestion(assessment_id=a.id, section_id=sec.id, question_id=q.id, order_index=i)
        db.add(aq)
        aqs.append(aq)
    await db.flush()
    return a, aqs, qs


def _judge0_up() -> bool:
    import httpx
    from app.core.config import get_settings
    try:
        return httpx.get(f"{get_settings().JUDGE0_URL}/about", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(not _judge0_up(), reason="BLOCKED: needs the Judge0 stack (code never runs unsandboxed)")
async def test_full_candidate_pipeline(client, monkeypatch):
    FakeLLM(monkeypatch, {"RubricEvaluation": rubric(0.7, 0.8)})
    async with AsyncSessionLocal() as db:
        org, rec, hr = await make_company(db)
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0), ("PostgreSQL", "required", 0.6, 0.8),
                                            ("Docker", "preferred", 0.4, 0.4)])
        st, stu_user, hs = await make_student(db)
        a, aqs, qs = await _published_assessment(db, org, job)
        await db.commit()

    r = await client.post("/applications", headers=hs, json={"job_id": str(job.id)})
    assert r.status_code == 200 and r.json()["status"] == "APPLIED" and r.json()["job_title"] == "Backend Developer"
    app_id = r.json()["id"]
    # the student view never includes answer keys or hidden tests
    detail = (await client.get(f"/assessments/{a.id}", headers=hs)).json()
    flat = [q["question"] for s in detail["sections"] for q in s["questions"]]
    assert all("correct_option_index" not in q and "test_cases" not in q for q in flat)

    attempt = (await client.post(f"/assessments/{a.id}/attempts", headers=hs, json={"application_id": app_id})).json()
    mcq, tech, code = aqs
    await client.put(f"/assessments/attempts/{attempt['id']}/answers", headers=hs,
                     json={"assessment_question_id": str(mcq.id), "selected_option_index": 1})
    await client.put(f"/assessments/attempts/{attempt['id']}/answers", headers=hs,
                     json={"assessment_question_id": str(tech.id), "answer_text": "When the predicate is selective..."})
    saved = (await client.put(f"/assessments/attempts/{attempt['id']}/answers", headers=hs,
                              json={"assessment_question_id": str(code.id), "answer_text": ""})).json()
    run = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": saved["answer_id"],
                                                                "question_id": str(qs[2].id), "language": "python", "source_code": SOLUTION})
    assert run.status_code == 200, run.text
    assert run.json()["passed_count"] == 3  # decided by Judge0, not an LLM
    wrong = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": saved["answer_id"],
                                                                  "question_id": str(qs[2].id), "language": "python",
                                                                  "source_code": "print(0)"})
    assert wrong.json()["passed_count"] == 1  # only the [0] case
    await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": saved["answer_id"],
                                                          "question_id": str(qs[2].id), "language": "python", "source_code": SOLUTION})

    sub = await client.post(f"/assessments/attempts/{attempt['id']}/submit", headers=hs)
    assert sub.status_code == 200 and sub.json()["status"] == "SCORED"
    assert sub.json()["total_score"] == pytest.approx((1 + 0.7 + 1) / 3)
    again = await client.post(f"/assessments/attempts/{attempt['id']}/submit", headers=hs)
    assert again.json()["total_score"] == sub.json()["total_score"]

    async with AsyncSessionLocal() as db:
        ev = (await db.scalars(select(SkillEvidence).where(SkillEvidence.student_id == st.id))).all()
        kinds = sorted(e.source_type for e in ev)
        assert kinds == ["CODING", "MCQ", "TECHNICAL_ASSESSMENT"]  # one row each; coding re-runs updated in place
        assert next(e for e in ev if e.source_type == "CODING").normalized_score == 1.0

    skills = {s["skill_name"]: s for s in (await client.get(f"/evidence/students/{st.id}/skills", headers=hs)).json()}
    assert skills["Python"]["estimated_level"] == pytest.approx((0.40 * 1.0 + 0.15 * 1.0) / 0.55)
    assert skills["PostgreSQL"]["estimated_level"] == pytest.approx(0.7)
    drill = (await client.get(f"/evidence/students/{st.id}/skills/{skills['Python']['skill_id']}", headers=hs)).json()
    assert drill["estimate"]["evidence_count"] == 2 and len(drill["evidence"]) == 2

    m = await client.post(f"/matching/applications/{app_id}/compute", headers=hr)
    assert m.status_code == 200
    body = m.json()
    assert body["matching_version"] == "matching_v1" and body["weights"]["required"] == 0.6
    expected_req = (min(1.0 / 0.6, 1) * 1.0 + min(0.7 / 0.6, 1) * 0.8) / 1.8
    assert body["required_skill_fit"] == pytest.approx(expected_req, abs=1e-3)
    assert body["preferred_skill_fit"] == 0.0 and any(s["skill_name"] == "Docker" for s in body["missing_skills"])
    assert 0 <= body["semantic_relevance"] <= 1

    hist = (await client.get(f"/applications/{app_id}/history", headers=hs)).json()
    assert [h["to"] for h in hist] == ["APPLIED", "ASSESSMENT_PENDING", "ASSESSMENT_COMPLETED"]
    notes = (await client.get("/me/notifications", headers=hs)).json()
    assert {"application_submitted", "assessment_assigned", "assessment_completed"} <= {n["event_type"] for n in notes}
    assert [n["event_type"] for n in notes].count("assessment_assigned") == 1  # starting the attempt must not re-notify
    async with AsyncSessionLocal() as db:
        actions = set((await db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id.in_([uuid.UUID(app_id), uuid.UUID(attempt["id"]), st.id]))) ).all())
    assert {"application_submitted", "application_status_changed", "assessment_submitted", "skill_profile_recalculated",
            "match_recalculated"} <= actions


@pytest.mark.asyncio
async def test_privacy_export_and_resume_delete(client):
    async with AsyncSessionLocal() as db:
        st, _, hs = await make_student(db)
        await db.commit()
    up = await client.post("/students/me/resume", headers=hs, files={"file": ("cv.txt", b"Python developer", "text/plain")})
    assert up.status_code == 200
    data = (await client.get("/me/data", headers=hs)).json()
    assert any(d["type"] == "RESUME" for d in data["documents"])
    d = await client.delete("/me/resume", headers=hs)
    assert d.json()["deleted_documents"] == 1
    data = (await client.get("/me/data", headers=hs)).json()
    assert not any(d["type"] == "RESUME" for d in data["documents"])
