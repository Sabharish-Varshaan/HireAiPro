import datetime as dt

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.accounts import InstitutionStudent
from app.models.assessments import Assessment
from app.models.enums import JobStatus
from app.models.institutions import Cohort, Department
from app.models.jobs import Job
from tests.factories import make_company, make_institution, make_job, make_student
from tests.integration.test_candidate_pipeline import _published_assessment

FUTURE = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=20)).isoformat()


@pytest.fixture
async def w():
    async with AsyncSessionLocal() as db:
        org, rec, hc = await make_company(db, "PostCo")
        org_b, rec_b, hb = await make_company(db, "PostCoB")
        inst, _, ho = await make_institution(db, "PostU")
        dep = Department(institution_id=inst.id, name="CS")
        db.add(dep)
        await db.flush()
        coh = Cohort(institution_id=inst.id, department_id=dep.id, name="C27", graduation_year=2027)
        db.add(coh)
        await db.flush()
        st, u, hs = await make_student(db, "S", institution=inst, cohort=coh)
        db.add(InstitutionStudent(institution_id=inst.id, user_id=u.id, email=u.email, status="ACTIVE", department_id=dep.id, cohort_id=coh.id, graduation_year=2027))
        _, _, hs_out = await make_student(db, "Out")
        await db.commit()
        return dict(org=str(org.id), hc=hc, hb=hb, ho=ho, hs=hs, hs_out=hs_out, inst=str(inst.id), rec=rec, orgobj=org)


INTERN = dict(title="Software Engineering Intern", employment_type="INTERNSHIP_TO_FULL_TIME", work_mode="ONSITE", location_city="Hyderabad",
              location_state="Telangana", location_country="India", internship_duration_value=6, internship_duration_unit="MONTH",
              compensation_currency="INR", compensation_min=35000, compensation_max=35000, compensation_period="MONTH", compensation_type="STIPEND",
              full_time_compensation_min=10, full_time_compensation_max=12, full_time_input_unit="LPA", number_of_openings=4,
              application_deadline=FUTURE, experience_level="FRESHER")


@pytest.mark.asyncio
async def test_create_serialize_and_reject_contradictions(client, w):
    r = await client.post(f"/jobs?organization_id={w['org']}", headers=w["hc"], json=INTERN)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["employment_type"], j["work_mode"], j["internship_duration_value"], j["internship_duration_unit"]) == ("INTERNSHIP_TO_FULL_TIME", "ONSITE", 6, "MONTH")
    assert (j["compensation_min"], j["full_time_compensation_min"], j["full_time_compensation_max"]) == ("35000.00", "1000000.00", "1200000.00")  # LPA normalized, lossless
    d = j["display"]
    assert d["headline"] == "Internship → Full-time · On-site · Hyderabad, Telangana, India"
    assert d["compensation"] == "₹35,000/month stipend" and d["internship_duration"] == "6 months" and d["full_time_package"] == "₹10–12 LPA"
    assert d["conversion"] == "Potential full-time conversion" and d["experience"] == "Fresher" and j["location"] == "Hyderabad, Telangana, India"
    for bad in ({"employment_type": "FULL_TIME", "internship_duration_value": 3, "internship_duration_unit": "MONTH"},
                {"employment_type": "INTERNSHIP"}, {"employment_type": "Full-time"}, {"work_mode": "ONSITE"},
                {"employment_type": "FULL_TIME", "compensation_currency": "USD", "compensation_min": 10, "compensation_period": "YEAR",
                 "compensation_type": "SALARY", "compensation_input_unit": "LPA"},
                {"number_of_openings": 0}, {"application_deadline": "2020-01-01T00:00:00+00:00"}):
        assert (await client.post(f"/jobs?organization_id={w['org']}", headers=w["hc"], json={"title": "x", **bad})).status_code == 422, bad
    assert (await client.post(f"/jobs?organization_id={w['org']}", headers=w["hb"], json={"title": "x"})).status_code == 403  # other company's org


@pytest.mark.asyncio
async def test_update_posting_publish_gate_freeze_and_deadline_extension(client, w):
    async with AsyncSessionLocal() as db:
        job = await make_job(db, w["orgobj"], w["rec"], [("Python", "required", 0.6, 1.0)], status=JobStatus.REQUIREMENTS_CONFIRMED)
        a, aqs, qs = await _published_assessment(db, w["orgobj"], job)
        await db.execute(update(Assessment).where(Assessment.id == a.id).values(status="DRAFT"))
        await db.commit()
        jid, aid = str(job.id), str(a.id)
    blocked = await client.post(f"/assessments/{aid}/publish", headers=w["hc"])
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "POSTING_INCOMPLETE"
    assert set(blocked.json()["detail"]["missing"]) == {"employment_type", "work_mode"}
    r = await client.put(f"/jobs/{jid}/posting", headers=w["hc"], json={"employment_type": "FULL_TIME", "work_mode": "HYBRID", "location_city": "Pune",
                                                                        "location_country": "India", "compensation_currency": "INR", "compensation_min": 12,
                                                                        "compensation_max": 15, "compensation_period": "YEAR", "compensation_type": "CTC",
                                                                        "compensation_input_unit": "LPA", "application_deadline": FUTURE})
    assert r.status_code == 200 and r.json()["display"]["compensation"] == "₹12–15 LPA"
    assert (await client.put(f"/jobs/{jid}/posting", headers=w["hb"], json={"employment_type": "FULL_TIME"})).status_code in (403, 404)
    assert (await client.post(f"/assessments/{aid}/publish", headers=w["hc"])).status_code == 200
    # published: only deadline and openings may change
    base = r.json()
    same = {"employment_type": "FULL_TIME", "work_mode": "HYBRID", "location_city": "Pune", "location_country": "India", "compensation_currency": "INR",
            "compensation_min": 12, "compensation_max": 15, "compensation_period": "YEAR", "compensation_type": "CTC", "compensation_input_unit": "LPA"}
    ext = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=40)).isoformat()
    ok = await client.put(f"/jobs/{jid}/posting", headers=w["hc"], json={**same, "application_deadline": ext, "number_of_openings": 5})
    assert ok.status_code == 200 and ok.json()["number_of_openings"] == 5
    changed = await client.put(f"/jobs/{jid}/posting", headers=w["hc"], json={**same, "compensation_min": 13, "application_deadline": ext})
    assert changed.status_code == 409


@pytest.mark.asyncio
async def test_deadline_is_enforced_by_the_server_and_extendable(client, w):
    async with AsyncSessionLocal() as db:
        job = await make_job(db, w["orgobj"], w["rec"], [("Python", "required", 0.6, 1.0)])
        job.employment_type, job.work_mode = "FULL_TIME", "REMOTE"
        job.application_deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)
        await db.commit()
        jid = str(job.id)
    await __import__("asyncio").sleep(1.3)
    seen = (await client.get(f"/jobs/{jid}", headers=w["hs_out"])).json()
    assert seen["display"]["applications_open"] is False  # listed and clearly closed
    closed = await client.post("/applications", headers=w["hs_out"], json={"job_id": jid})
    assert closed.status_code == 409 and closed.json()["detail"]["code"] == "APPLICATIONS_CLOSED"
    ext = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).isoformat()
    assert (await client.put(f"/jobs/{jid}/posting", headers=w["hc"], json={"employment_type": "FULL_TIME", "work_mode": "REMOTE", "application_deadline": ext})).status_code == 200
    assert (await client.post("/applications", headers=w["hs_out"], json={"job_id": jid})).status_code == 200  # recruiter extended it


@pytest.mark.asyncio
async def test_student_and_officer_see_exactly_what_the_recruiter_entered_and_filters(client, w):
    j = (await client.post(f"/jobs?organization_id={w['org']}", headers=w["hc"], json=INTERN)).json()
    ft = (await client.post(f"/jobs?organization_id={w['org']}", headers=w["hc"], json={"title": "Backend Engineer", "employment_type": "FULL_TIME", "work_mode": "REMOTE"})).json()
    async with AsyncSessionLocal() as db:  # both published (bypassing the assessment step; that path is covered above)
        for jid in (j["id"], ft["id"]):
            row = await db.get(Job, jid)
            row.status = JobStatus.PUBLISHED
        row = await db.get(Job, j["id"])
        row.distribution_type, row.target_institution_id, row.institution_approval = "INSTITUTION", w["inst"], "PENDING"
        await db.commit()
    # officer sees the full picture before deciding
    ops = (await client.get(f"/institutions/{w['inst']}/opportunities", headers=w["ho"], params={"status": "PENDING"})).json()
    o = next(x for x in ops if x["job_id"] == j["id"])
    assert o["display"]["headline"].startswith("Internship → Full-time · On-site") and o["display"]["compensation"] == "₹35,000/month stipend"
    assert o["display"]["internship_duration"] == "6 months" and o["display"]["full_time_package"] == "₹10–12 LPA" and o["display"]["application_deadline"]
    assert o["number_of_openings"] == 4 and o["skills"] is not None
    approve = await client.post(f"/institutions/{w['inst']}/opportunities/{j['id']}/approve", headers=w["ho"], json={"cohort_ids": []})
    assert approve.status_code == 200
    # eligible student: identical values; outsider cannot see the campus job but sees the open-market one
    sj = (await client.get(f"/jobs/{j['id']}", headers=w["hs"])).json()
    assert sj["display"] == j["display"]  # the student sees exactly what the recruiter entered
    assert sj["employment_type"] == "INTERNSHIP_TO_FULL_TIME" and sj["compensation_min"] == "35000.00" and sj["internship_duration_value"] == 6
    assert (await client.get(f"/jobs/{j['id']}", headers=w["hs_out"])).status_code == 404
    lst = (await client.get("/jobs", headers=w["hs"], params={"employment_type": "INTERNSHIP_TO_FULL_TIME"})).json()
    assert [x["id"] for x in lst] == [j["id"]]
    assert ft["id"] in {x["id"] for x in (await client.get("/jobs", headers=w["hs"], params={"work_mode": "REMOTE"})).json()}
    assert j["id"] not in {x["id"] for x in (await client.get("/jobs", headers=w["hs"], params={"work_mode": "REMOTE"})).json()}
    assert "full_time_compensation" not in str(await client.get("/jobs", headers=w["hs_out"]))  # nothing leaks to non-eligible students
