import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.accounts import InstitutionStudent
from app.models.enums import ApplicationStatus, JobStatus
from app.models.institutions import Cohort, Department
from app.models.jobs import Job
from tests.factories import make_company, make_institution, make_job, make_student


async def _student(db, inst, dep, cohort, year, name):
    from app.models.students import StudentProfile  # noqa: F401
    st, u, h = await make_student(db, name, institution=inst, cohort=cohort)
    db.add(InstitutionStudent(institution_id=inst.id, user_id=u.id, email=u.email, status="ACTIVE", department_id=dep.id if dep else None,
                              cohort_id=cohort.id if cohort else None, graduation_year=year))
    return h


@pytest.fixture
async def ctx():
    async with AsyncSessionLocal() as db:
        inst, _, ho = await make_institution(db, "CampusU")
        other, _, ho2 = await make_institution(db, "RivalU")
        cs = Department(institution_id=inst.id, name="CS")
        me = Department(institution_id=inst.id, name="Mech")
        db.add_all([cs, me])
        await db.flush()
        c27 = Cohort(institution_id=inst.id, department_id=cs.id, name="CSE27", graduation_year=2027)
        c26 = Cohort(institution_id=inst.id, department_id=me.id, name="ME26", graduation_year=2026)
        db.add_all([c27, c26])
        await db.flush()
        eligible = await _student(db, inst, cs, c27, 2027, "Eligible")
        wrong_cohort = await _student(db, inst, me, c26, 2026, "WrongCohort")
        outsider_st, _, outsider = await make_student(db, "Outsider")
        org, rec, hc = await make_company(db, "CampusCo")
        org_b, _, hb = await make_company(db, "RivalCo")
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        job.status = JobStatus.PUBLISHED
        open_job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        open_job.status = JobStatus.PUBLISHED
        await db.commit()
        return dict(inst=str(inst.id), other=str(other.id), job=str(job.id), open_job=str(open_job.id), cs=str(cs.id), c27=str(c27.id),
                    ho=ho, ho2=ho2, hc=hc, hb=hb, eligible=eligible, wrong=wrong_cohort, outsider=outsider)


async def _visible(client, h, job_id):
    lst = (await client.get("/jobs", headers=h)).json()
    return job_id in {j["id"] for j in lst}


@pytest.mark.asyncio
async def test_institution_opportunity_lifecycle_and_deterministic_eligibility(client, ctx):
    j = ctx["job"]
    assert (await client.put(f"/jobs/{j}/distribution", headers=ctx["hb"], json={"distribution_type": "INSTITUTION", "institution_id": ctx["inst"]})).status_code == 403  # not its company
    r = await client.put(f"/jobs/{j}/distribution", headers=ctx["hc"], json={"distribution_type": "INSTITUTION", "institution_id": ctx["inst"]})
    assert r.status_code == 200 and r.json()["institution_approval"] == "PENDING"
    # pending: invisible and unappliable for everyone, including students of that institution
    for h in (ctx["eligible"], ctx["wrong"], ctx["outsider"]):
        assert not await _visible(client, h, j)
        assert (await client.get(f"/jobs/{j}", headers=h)).status_code == 404
        assert (await client.post("/applications", headers=h, json={"job_id": j})).status_code == 404
    assert await _visible(client, ctx["outsider"], ctx["open_job"])  # open market unaffected
    base = f"/institutions/{ctx['inst']}/opportunities"
    pend = (await client.get(base, headers=ctx["ho"], params={"status": "PENDING"})).json()
    assert [p["job_id"] for p in pend] == [j] and pend[0]["company"]
    assert "assessment" not in str(pend).lower()  # officer sees the opportunity, not private assessment content
    assert (await client.get(base, headers=ctx["ho2"])).status_code == 404  # other institution
    assert (await client.post(f"{base}/{j}/approve", headers=ctx["ho2"], json={})).status_code == 404
    assert (await client.post(f"{base}/{j}/approve", headers=ctx["hc"], json={})).status_code == 403
    bad = await client.post(f"/institutions/{ctx['other']}/opportunities/{j}/approve", headers=ctx["ho2"], json={})
    assert bad.status_code == 404  # job targets a different institution
    ok = await client.post(f"{base}/{j}/approve", headers=ctx["ho"], json={"cohort_ids": [ctx["c27"]], "graduation_years": [2027]})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    assert await _visible(client, ctx["eligible"], j)
    assert not await _visible(client, ctx["wrong"], j)  # right institution, wrong cohort/year
    assert not await _visible(client, ctx["outsider"], j)  # no institution
    assert (await client.post("/applications", headers=ctx["wrong"], json={"job_id": j})).status_code == 404
    assert (await client.post("/applications", headers=ctx["eligible"], json={"job_id": j})).status_code == 200
    assert (await client.put(f"/jobs/{j}/distribution", headers=ctx["hc"], json={"distribution_type": "OPEN_MARKET"})).status_code == 409
    assert (await client.post(f"{base}/{j}/approve", headers=ctx["ho"], json={})).status_code == 409  # not pending anymore


@pytest.mark.asyncio
async def test_rejection_and_department_rules(client, ctx):
    j = ctx["open_job"]
    await client.put(f"/jobs/{j}/distribution", headers=ctx["hc"], json={"distribution_type": "INSTITUTION", "institution_id": ctx["inst"]})
    base = f"/institutions/{ctx['inst']}/opportunities"
    assert (await client.post(f"{base}/{j}/reject", headers=ctx["ho"], json={"note": "x"})).status_code == 422
    assert (await client.post(f"{base}/{j}/reject", headers=ctx["ho"], json={"note": "Not relevant to our cohorts"})).status_code == 200
    mine = (await client.get(f"/jobs/{j}", headers=ctx["hc"])).json()
    assert mine["institution_approval"] == "REJECTED"
    assert not await _visible(client, ctx["eligible"], j)
    # rejected -> company can re-target to open market and it becomes visible to all
    assert (await client.put(f"/jobs/{j}/distribution", headers=ctx["hc"], json={"distribution_type": "OPEN_MARKET"})).status_code == 200
    assert await _visible(client, ctx["outsider"], j)
    # department rule
    j2 = ctx["job"]
    await client.put(f"/jobs/{j2}/distribution", headers=ctx["hc"], json={"distribution_type": "INSTITUTION", "institution_id": ctx["inst"]})
    assert (await client.post(f"{base}/{j2}/approve", headers=ctx["ho"], json={"department_ids": [ctx["cs"]]})).status_code == 200
    assert await _visible(client, ctx["eligible"], j2) and not await _visible(client, ctx["wrong"], j2)
