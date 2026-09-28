import pytest

from app.core.database import AsyncSessionLocal
from app.models.enums import ApplicationStatus, EvidenceSourceType, JobStatus, UserRole
from app.services.evidence.service import record_evidence
from tests.factories import (make_application, make_company, make_institution, make_job, make_student, make_user, skill)
from app.models.institutions import Cohort


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client):
    for path in ("/jobs", "/questions", "/admin/stats", "/applications/mine", "/me/notifications"):
        assert (await client.get(path)).status_code == 401, path


@pytest.mark.asyncio
async def test_role_enforcement(client):
    async with AsyncSessionLocal() as db:
        _, hs = await make_user(db, UserRole.STUDENT)
        org, _, hr = await make_company(db)
        await db.commit()
    assert (await client.get("/admin/stats", headers=hs)).status_code == 403
    assert (await client.get("/admin/stats", headers=hr)).status_code == 403
    assert (await client.post("/questions", headers=hs, json={"question_text": "x" * 20, "skill": "Python"})).status_code == 403
    assert (await client.post(f"/jobs?organization_id={org.id}", headers=hs, json={"title": "x"})).status_code == 403
    assert (await client.post("/admin/skills", headers=hr, json={"canonical_name": "Hax", "category": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_company_b_cannot_touch_company_a_jobs_or_candidates(client):
    async with AsyncSessionLocal() as db:
        org_a, rec_a, ha = await make_company(db, "A")
        org_b, rec_b, hb = await make_company(db, "B")
        job_a = await make_job(db, org_a, rec_a, [("Python", "required", 0.6, 1.0)], status=JobStatus.SKILLS_EXTRACTED)
        pub_a = await make_job(db, org_a, rec_a, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db)
        app_a = await make_application(db, pub_a, st, ApplicationStatus.UNDER_REVIEW)
        await record_evidence(db, st.id, (await skill(db, "Python")).id, EvidenceSourceType.MCQ, 0.8, idempotency_key=f"x{st.id}")
        await db.commit()
    # unpublished job invisible to other tenants and students
    assert (await client.get(f"/jobs/{job_a.id}", headers=hb)).status_code == 404
    assert (await client.get(f"/jobs/{job_a.id}", headers=hs)).status_code == 404
    assert (await client.get(f"/jobs/{job_a.id}", headers=ha)).status_code == 200
    assert (await client.post(f"/jobs?organization_id={org_a.id}", headers=hb, json={"title": "x"})).status_code == 403
    assert (await client.post(f"/jobs/{job_a.id}/process", headers=hb)).status_code == 403
    assert (await client.put(f"/jobs/{job_a.id}/requirements/confirm", headers=hb, json={"skills": []})).status_code == 403
    assert (await client.get(f"/applications/job/{pub_a.id}", headers=hb)).status_code == 403
    assert (await client.get(f"/matching/jobs/{pub_a.id}/ranked", headers=hb)).status_code == 403
    assert (await client.put(f"/applications/{app_a.id}/status", headers=hb, json={"status": "SHORTLISTED"})).status_code == 403
    # candidate data: B has no relationship with this student
    assert (await client.get(f"/evidence/students/{st.id}/skills", headers=hb)).status_code == 403
    assert (await client.get(f"/evidence/students/{st.id}/skills", headers=ha)).status_code == 200
    # recruiter can make decisions, but only allowed ones
    assert (await client.put(f"/applications/{app_a.id}/status", headers=ha, json={"status": "OFFER"})).status_code == 409
    assert (await client.put(f"/applications/{app_a.id}/status", headers=ha, json={"status": "INTERVIEW_COMPLETED"})).status_code == 403
    r = await client.put(f"/applications/{app_a.id}/status", headers=ha, json={"status": "SHORTLISTED"})
    assert r.status_code == 200 and r.json()["status"] == "SHORTLISTED"


@pytest.mark.asyncio
async def test_students_cannot_read_each_other(client):
    async with AsyncSessionLocal() as db:
        s1, _, h1 = await make_student(db)
        s2, _, _ = await make_student(db)
        await db.commit()
    assert (await client.get(f"/evidence/students/{s2.id}/evidence", headers=h1)).status_code == 403
    assert (await client.get(f"/students/{s2.id}", headers=h1)).status_code == 403
    assert (await client.get(f"/evidence/students/{s1.id}/evidence", headers=h1)).status_code == 200


@pytest.mark.asyncio
async def test_institution_isolation(client):
    async with AsyncSessionLocal() as db:
        inst_x, _, hx = await make_institution(db, "X")
        inst_y, _, hy = await make_institution(db, "Y")
        c = Cohort(institution_id=inst_y.id, name="Y-2027")
        db.add(c)
        await db.flush()
        st_y, _, _ = await make_student(db, institution=inst_y, cohort=c)
        await db.commit()
    for path in (f"/institutions/{inst_y.id}/roster", f"/institutions/{inst_y.id}/analytics", f"/institutions/{inst_y.id}/structure"):
        assert (await client.get(path, headers=hx)).status_code == 404, path
        assert (await client.get(path, headers=hy)).status_code == 200, path
    assert (await client.get(f"/evidence/students/{st_y.id}/skills", headers=hx)).status_code == 403
    assert (await client.get(f"/evidence/students/{st_y.id}/skills", headers=hy)).status_code == 200


@pytest.mark.asyncio
async def test_platform_admin_cannot_be_self_registered(client):
    r = await client.post("/auth/signup", json={"email": "x-admin@example.com", "password": "password123",
                                                "full_name": "x", "role": "PLATFORM_ADMIN"})
    assert r.status_code == 400 and "cannot be self-registered" in r.text


@pytest.mark.asyncio
async def test_deactivated_skill_is_not_offered_in_search(client):
    from app.models.skills import Skill, SkillAlias
    from tests.factories import uniq

    async with AsyncSessionLocal() as db:
        _, hr = await make_user(db, UserRole.RECRUITER)
        name = uniq("Retired Skill")
        sk = Skill(canonical_name=name, category="x", is_active=False)
        db.add(sk)
        await db.flush()
        db.add(SkillAlias(skill_id=sk.id, alias=name.lower() + "-alias", alias_normalized=name.lower() + "-alias"))
        await db.commit()
    assert (await client.get("/skills", params={"q": name}, headers=hr)).json() == []
    assert (await client.get("/skills", params={"q": name.lower() + "-alias"}, headers=hr)).json() == []
    assert "Go" in [s["canonical_name"] for s in (await client.get("/skills", params={"q": "golang"}, headers=hr)).json()]


@pytest.mark.asyncio
async def test_deactivated_user_is_locked_out(client):
    async with AsyncSessionLocal() as db:
        admin, ha = await make_user(db, UserRole.PLATFORM_ADMIN)
        victim, hv = await make_user(db, UserRole.RECRUITER)
        _, hs = await make_user(db, UserRole.STUDENT)
        await db.commit()
    assert (await client.get("/auth/me", headers=hv)).status_code == 200
    assert (await client.patch(f"/admin/users/{victim.id}", headers=hs, json={"is_active": False})).status_code == 403
    assert (await client.patch(f"/admin/users/{admin.id}", headers=ha, json={"is_active": False})).status_code == 400
    assert (await client.patch(f"/admin/users/{victim.id}", headers=ha, json={"is_active": False})).status_code == 200
    assert (await client.get("/auth/me", headers=hv)).status_code == 401  # existing token stops working
    assert (await client.get("/jobs", headers=hv)).status_code == 401
    assert (await client.patch(f"/admin/users/{victim.id}", headers=ha, json={"is_active": True})).status_code == 200
    assert (await client.get("/auth/me", headers=hv)).status_code == 200
