"""Three-role boundaries: student / company / placement officer."""
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.assessments import AssessmentAnswer
from app.models.enums import ApplicationStatus
from tests.factories import make_application, make_company, make_institution, make_job, make_student
from tests.integration.test_candidate_pipeline import _published_assessment


@pytest.fixture
async def world():
    async with AsyncSessionLocal() as db:
        inst_a, _, ho_a = await make_institution(db, "BoundA")
        inst_b, _, ho_b = await make_institution(db, "BoundB")
        org_a, rec_a, hc_a = await make_company(db, "CoA")
        org_b, rec_b, hc_b = await make_company(db, "CoB")
        job_a = await make_job(db, org_a, rec_a, [("Python", "required", 0.6, 1.0)])
        st1, _, hs1 = await make_student(db, "S1", institution=inst_a)
        st2, _, hs2 = await make_student(db, "S2", institution=inst_b)
        st3, _, hs3 = await make_student(db, "S3")  # never applied anywhere
        app1 = await make_application(db, job_a, st1, ApplicationStatus.APPLIED)
        a, aqs, qs = await _published_assessment(db, org_a, job_a)
        await db.commit()
        return dict(ho_a=ho_a, ho_b=ho_b, hc_a=hc_a, hc_b=hc_b, hs1=hs1, hs2=hs2, hs3=hs3, app1=str(app1.id), a=str(a.id), aqs=aqs,
                    inst_a=str(inst_a.id), inst_b=str(inst_b.id), st1=str(st1.id), st3=str(st3.id), job_a=str(job_a.id))


@pytest.mark.asyncio
async def test_student_cannot_reach_company_or_officer_endpoints(client, world):
    w = world
    for method, path, body in [("GET", f"/proctoring/review/by-application/{w['app1']}", None), ("GET", f"/interviews/templates/by-job/{w['job_a']}", None),
                               ("PUT", f"/jobs/{w['job_a']}/distribution", {"distribution_type": "OPEN_MARKET"}),
                               ("GET", f"/institutions/{w['inst_a']}/overview", None), ("GET", f"/institutions/{w['inst_a']}/opportunities", None),
                               ("PUT", f"/applications/{w['app1']}/status", {"status": "SHORTLISTED"}),
                               ("PUT", f"/assessments/{w['a']}/config", {"duration_minutes": 30})]:
        r = await (client.get(path, headers=w["hs1"]) if method == "GET" else client.put(path, headers=w["hs1"], json=body))
        assert r.status_code in (403, 404), (path, r.status_code)
    async with AsyncSessionLocal() as db:  # and the application really is untouched
        from app.models.applications import Application
        assert (await db.get(Application, w["app1"])).status == ApplicationStatus.APPLIED


@pytest.mark.asyncio
async def test_company_a_cannot_see_company_b_candidates_or_unrelated_students(client, world):
    w = world
    assert (await client.get(f"/assessments/attempts/by-application/{w['app1']}", headers=w["hc_a"])).status_code == 200  # own candidate
    assert (await client.get(f"/assessments/attempts/by-application/{w['app1']}", headers=w["hc_b"])).status_code in (403, 404)
    assert (await client.get(f"/proctoring/review/by-application/{w['app1']}", headers=w["hc_b"])).status_code in (403, 404)
    assert (await client.put(f"/applications/{w['app1']}/status", headers=w["hc_b"], json={"status": "REJECTED"})).status_code in (403, 404)
    # a company can read skills only of students who applied to ITS jobs
    assert (await client.get(f"/evidence/students/{w['st1']}/skills", headers=w["hc_a"])).status_code == 200
    assert (await client.get(f"/evidence/students/{w['st3']}/skills", headers=w["hc_a"])).status_code == 403
    assert (await client.get(f"/evidence/students/{w['st1']}/skills", headers=w["hc_b"])).status_code == 403
    for path in (f"/institutions/{w['inst_a']}/student-records", f"/institutions/{w['inst_a']}/roster", f"/institutions/{w['inst_a']}/overview"):
        assert (await client.get(path, headers=w["hc_a"])).status_code == 403  # companies have no institution access at all


@pytest.mark.asyncio
async def test_officer_of_institution_a_cannot_touch_institution_b_or_its_students(client, world):
    w = world
    for path in (f"/institutions/{w['inst_b']}/student-records", f"/institutions/{w['inst_b']}/overview", f"/institutions/{w['inst_b']}/opportunities",
                 f"/institutions/{w['inst_b']}/roster"):
        assert (await client.get(path, headers=w["ho_a"])).status_code == 404, path
    assert (await client.post(f"/institutions/{w['inst_b']}/student-records/invite", headers=w["ho_a"], json={"email": "x@example.com"})).status_code == 404
    assert (await client.get(f"/evidence/students/{w['st1']}/skills", headers=w["ho_b"])).status_code == 403  # B's officer, A's student
    assert (await client.get(f"/evidence/students/{w['st1']}/skills", headers=w["ho_a"])).status_code == 200


@pytest.mark.asyncio
async def test_student_cannot_set_own_score_and_cannot_touch_another_students_attempt(client, world):
    w = world
    att = (await client.post(f"/assessments/{w['a']}/attempts", headers=w["hs1"], json={"application_id": w["app1"]})).json()
    mcq = w["aqs"][0]
    r = await client.put(f"/assessments/attempts/{att['id']}/answers", headers=w["hs1"],
                         json={"assessment_question_id": str(mcq.id), "selected_option_index": 0, "score": 1.0, "is_correct": True, "total_score": 1.0})
    assert r.status_code == 200
    async with AsyncSessionLocal() as db:
        ans = await db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == att["id"]))
        assert ans.score is None and ans.is_correct is None  # extra fields are ignored; only the grader writes scores
    # another student: no session, no autosave, no submit, no coding run
    for m, path, body in [("GET", f"/assessments/attempts/{att['id']}", None),
                          ("PUT", f"/assessments/attempts/{att['id']}/answers", {"assessment_question_id": str(mcq.id), "selected_option_index": 1}),
                          ("POST", f"/assessments/attempts/{att['id']}/submit", None)]:
        r = await (client.get(path, headers=w["hs2"]) if m == "GET" else client.put(path, headers=w["hs2"], json=body) if m == "PUT"
                   else client.post(path, headers=w["hs2"]))
        assert r.status_code in (403, 404), (path, r.status_code)
    # and cannot start an attempt for someone else's application
    assert (await client.post(f"/assessments/{w['a']}/attempts", headers=w["hs2"], json={"application_id": w["app1"]})).status_code in (403, 404)


@pytest.mark.asyncio
async def test_another_company_or_staff_cannot_read_a_company_job_even_when_published(client, world):
    """Found by the Chrome cross-company test: any non-student could read ANY published job, including one still awaiting institution approval."""
    w = world
    async with AsyncSessionLocal() as db:
        from app.models.jobs import Job
        j = await db.get(Job, w["job_a"])
        j.distribution_type, j.target_institution_id, j.institution_approval = "INSTITUTION", w["inst_a"], "PENDING"
        await db.commit()
    assert (await client.get(f"/jobs/{w['job_a']}", headers=w["hc_a"])).status_code == 200            # owner
    assert (await client.get(f"/jobs/{w['job_a']}", headers=w["hc_b"])).status_code == 404            # competitor
    assert (await client.get(f"/jobs/{w['job_a']}", headers=w["ho_b"])).status_code == 404            # other institution's officer
    assert w["job_a"] not in {x["id"] for x in (await client.get("/jobs", headers=w["hc_b"])).json()}  # unfiltered list is own company only
    assert w["job_a"] in {x["id"] for x in (await client.get("/jobs", headers=w["hc_a"])).json()}
    async with AsyncSessionLocal() as db:  # open-market published job: still not readable by another company
        j = await db.get(Job, w["job_a"])
        j.distribution_type, j.target_institution_id, j.institution_approval = "OPEN_MARKET", None, "NOT_REQUIRED"
        await db.commit()
    assert (await client.get(f"/jobs/{w['job_a']}", headers=w["hc_b"])).status_code == 404
    assert (await client.get(f"/jobs/{w['job_a']}", headers=w["hs3"])).status_code == 200            # students still see open-market jobs
