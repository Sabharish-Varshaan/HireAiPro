"""Score visibility is enforced at the API (docs/SCORE_VISIBILITY.md): a student's
own responses contain no hiring numbers; the hiring company, an authorized
institution and admins do; other tenants get nothing."""
import pytest

from app.core.database import AsyncSessionLocal
from app.models.applications import Application
from app.models.assessments import AssessmentAnswer, AssessmentAttempt
from app.models.enums import ApplicationStatus, AssessmentAttemptStatus
from app.models.interviews import Interview, InterviewTurn
from app.models.matching import Match
from tests.factories import make_application, make_company, make_institution, make_job, make_student, skill
from tests.integration.test_candidate_pipeline import _published_assessment

RESTRICTED = {"score", "total_score", "match_score", "required_skill_fit", "preferred_skill_fit", "evidence_confidence",
              "semantic_relevance", "rubric_evaluation", "estimated_level", "confidence", "normalized_score",
              "raw_score", "reason_for_question", "passed_count", "is_correct", "overall_score", "weights"}


def _keys(obj, found=None):
    found = set() if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            _keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, found)
    return found


@pytest.fixture
async def world():
    async with AsyncSessionLocal() as db:
        inst, _, hi = await make_institution(db, "Enrolled U")
        _, _, hi_other = await make_institution(db, "Other U")
        org_a, rec_a, ha = await make_company(db, "A")
        org_b, rec_b, hb = await make_company(db, "B")
        job_a = await make_job(db, org_a, rec_a, [("Python", "required", 0.6, 1.0)])
        job_b = await make_job(db, org_b, rec_b, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db, institution=inst)
        app_a = await make_application(db, job_a, st, ApplicationStatus.UNDER_REVIEW)
        await make_application(db, job_b, st, ApplicationStatus.APPLIED)  # student also applied to B
        a, aqs, qs = await _published_assessment(db, org_a, job_a)
        att = AssessmentAttempt(assessment_id=a.id, application_id=app_a.id, student_id=st.id,
                                status=AssessmentAttemptStatus.SCORED, total_score=0.66)
        db.add(att)
        await db.flush()
        db.add(AssessmentAnswer(attempt_id=att.id, assessment_question_id=aqs[1].id, answer_text="x", score=0.9,
                                rubric_evaluation={"overall_score": 0.9}))
        py = await skill(db, "Python")
        iv = Interview(application_id=app_a.id, student_id=st.id, job_id=job_a.id, max_turns=3, status="COMPLETED")
        db.add(iv)
        await db.flush()
        db.add(InterviewTurn(interview_id=iv.id, turn_index=0, target_skill_id=py.id, question_text="Explain GC.",
                             difficulty="hard", reason_for_question="[required, importance 0.9, confidence 0.71, asked 0x]",
                             student_answer_text="refcounting", rubric_evaluation={"concept_accuracy": 0.9, "overall_score": 0.93}))
        db.add(Match(application_id=app_a.id, job_id=job_a.id, student_id=st.id, match_score=0.749, required_skill_fit=0.68,
                     preferred_skill_fit=1.0, evidence_confidence=0.69, semantic_relevance=0.7,
                     strong_skills=[{"skill_name": "Python", "fit": 1.0}], partial_skills=[], missing_skills=[],
                     matching_version="matching_v1"))
        await db.commit()
    return dict(app=app_a.id, iv=iv.id, st=st.id, hs=hs, ha=ha, hb=hb, hi=hi, hi_other=hi_other)


def _paths(w):
    return [f"/applications/{w['app']}", f"/applications/{w['app']}/history",
            f"/assessments/attempts/by-application/{w['app']}", f"/interviews/by-application/{w['app']}",
            f"/interviews/{w['iv']}/turns", f"/matching/applications/{w['app']}",
            f"/evidence/students/{w['st']}/skills", f"/evidence/students/{w['st']}/evidence", "/applications/mine", "/me/data"]


@pytest.mark.asyncio
async def test_student_responses_contain_no_hiring_numbers(client, world):
    for path in _paths(world):
        r = await client.get(path, headers=world["hs"])
        assert r.status_code == 200, (path, r.text)
        leaked = _keys(r.json()) & RESTRICTED
        assert not leaked, f"{path} leaked {leaked}"
        assert "0.749" not in r.text and "0.66" not in r.text and "0.93" not in r.text, path
    m = (await client.get(f"/matching/applications/{world['app']}", headers=world["hs"])).json()
    assert m["strengths"] == ["Python"]  # qualitative developmental feedback is allowed


@pytest.mark.asyncio
async def test_hiring_company_sees_scores(client, world):
    att = (await client.get(f"/assessments/attempts/by-application/{world['app']}", headers=world["ha"])).json()
    assert att["attempt"]["total_score"] == pytest.approx(0.66) and any(a.get("score") == 0.9 for a in att["answers"])
    m = (await client.get(f"/matching/applications/{world['app']}", headers=world["ha"])).json()
    assert m["match_score"] == pytest.approx(0.749) and "required_skill_fit" in m
    turns = (await client.get(f"/interviews/{world['iv']}/turns", headers=world["ha"])).json()
    assert turns[0]["rubric_evaluation"]["overall_score"] == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_other_company_cannot_read_company_a_evaluation(client, world):
    # company B has a legitimate application from this student, but not to this job
    for path in [f"/applications/{world['app']}", f"/applications/{world['app']}/history",
                 f"/assessments/attempts/by-application/{world['app']}", f"/interviews/by-application/{world['app']}",
                 f"/interviews/{world['iv']}/turns", f"/matching/applications/{world['app']}"]:
        r = await client.get(path, headers=world["hb"])
        assert r.status_code in (403, 404), (path, r.status_code, r.text[:120])


@pytest.mark.asyncio
async def test_enrolled_institution_sees_permitted_scores_and_other_institution_is_denied(client, world):
    att = (await client.get(f"/assessments/attempts/by-application/{world['app']}", headers=world["hi"])).json()
    assert att["attempt"]["total_score"] == pytest.approx(0.66)
    skills = await client.get(f"/evidence/students/{world['st']}/skills", headers=world["hi"])
    assert skills.status_code == 200
    for path in [f"/assessments/attempts/by-application/{world['app']}", f"/matching/applications/{world['app']}",
                 f"/evidence/students/{world['st']}/skills", f"/interviews/{world['iv']}/turns"]:
        r = await client.get(path, headers=world["hi_other"])
        assert r.status_code in (403, 404), (path, r.status_code)
