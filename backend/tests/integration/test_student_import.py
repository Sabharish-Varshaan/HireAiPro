import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.accounts import EmailOutbox, InstitutionStudent
from app.models.institutions import Cohort, Department
from app.models.students import StudentProfile
from app.models.users import User
from tests.factories import make_institution, make_student, uniq

PW = "Correct-horse-9"


@pytest.fixture
async def ctx(client):
    async with AsyncSessionLocal() as db:
        inst, po, h = await make_institution(db, "ImpU")
        other, _, h2 = await make_institution(db, "OtherImp")
        dep = Department(institution_id=inst.id, name="Computer Science")
        db.add(dep)
        await db.flush()
        coh = Cohort(institution_id=inst.id, department_id=dep.id, name="CSE 2027", graduation_year=2027)
        db.add(coh)
        existing_p, existing_u, _ = await make_student(db, "Exists")  # independent student account
        elsewhere_p, elsewhere_u, _ = await make_student(db, "Elsewhere", institution=other)
        await db.commit()
        return dict(h=h, h_other=h2, iid=str(inst.id), existing=existing_u.email, elsewhere=elsewhere_u.email)


def _csv(rows):
    head = "student_id,first_name,last_name,email,department,program,cohort,graduation_year\n"
    return ("f.csv", (head + "\n".join(rows)).encode(), "text/csv")


@pytest.mark.asyncio
async def test_preview_reports_row_errors_and_confirm_imports_valid_rows(client, ctx):
    new1, new2 = f"{uniq('n')}@example.com", f"{uniq('n')}@example.com"
    rows = [f"S1,Ada,L,{new1},Computer Science,BTech,CSE 2027,2027",
            f"S2,Bob,K,{new2},,,,",
            f"S3,Cy,M,{ctx['existing']},Computer Science,,,",
            "S4,Bad,Email,not-an-email,,,,",
            f"S5,Dee,N,{uniq('d')}@example.com,Astrology,,,",
            f"S6,Eve,O,{uniq('e')}@example.com,,,Nope 2030,",
            f"S7,Fay,P,{new1},,,,",
            f"S8,Gus,Q,{ctx['elsewhere']},,,,",
            f"S9,Hal,R,{uniq('h')}@example.com,,,,abcd"]
    base = f"/institutions/{ctx['iid']}/student-records"
    pv = (await client.post(f"{base}/import/preview", headers=ctx["h"], files={"file": _csv(rows)})).json()
    assert (pv["total"], pv["invite"], pv["link_existing"], pv["errors"]) == (9, 2, 1, 6), [r for r in pv["rows"] if r["error"]]
    errs = {r["line"]: r["error"] for r in pv["rows"] if r["error"]}
    assert set(errs) == {5, 6, 7, 8, 9, 10}  # header is line 1; every bad row named explicitly
    assert "Unknown department" in errs[6] and "Unknown cohort" in errs[7] and "Duplicate" in errs[8] and "another institution" in errs[9]
    async with AsyncSessionLocal() as db:  # preview wrote nothing
        assert not (await db.scalars(select(InstitutionStudent).where(InstitutionStudent.email == new1))).first()
    done = (await client.post(f"{base}/import/confirm", headers=ctx["h"], files={"file": _csv(rows)})).json()
    assert (done["invited"], done["linked"], done["errors"]) == (2, 1, 6)
    async with AsyncSessionLocal() as db:
        n1 = await db.scalar(select(InstitutionStudent).where(InstitutionStudent.email == new1))
        assert n1.status == "PENDING" and n1.user_id is None and n1.graduation_year == 2027 and n1.department_id and n1.cohort_id
        assert not await db.scalar(select(User).where(User.email == new1))  # no account and no password until claimed
        ex = await db.scalar(select(InstitutionStudent).where(InstitutionStudent.email == ctx["existing"]))
        assert ex.status == "ACTIVE"
        u = await db.scalar(select(User).where(User.email == ctx["existing"]))
        p = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == u.id))
        assert str(p.institution_id) == ctx["iid"]
        assert len((await db.scalars(select(User).where(User.email == ctx["existing"]))).all()) == 1  # no duplicate user
        assert (await db.scalars(select(EmailOutbox).where(EmailOutbox.to_email == new2))).first()
    lst = await client.get(base, headers=ctx["h"])
    assert lst.json()["counts"] == {"PENDING": 2, "ACTIVE": 1, "DISABLED": 0}
    again = (await client.post(f"{base}/import/preview", headers=ctx["h"], files={"file": _csv(rows[:2])})).json()
    assert [r["error"] for r in again["rows"]] == ["Already invited; use Resend Invite"] * 2


@pytest.mark.asyncio
async def test_resend_disable_enable_and_isolation(client, ctx):
    base = f"/institutions/{ctx['iid']}/student-records"
    email = f"{uniq('one')}@example.com"
    r = await client.post(f"{base}/invite", headers=ctx["h"], json={"email": email, "first_name": "Zed", "department": "Computer Science"})
    assert r.status_code == 200 and r.json()["action"] == "INVITE"
    sid = r.json()["id"]
    assert (await client.post(f"{base}/invite", headers=ctx["h"], json={"email": email})).status_code == 422
    assert (await client.post(f"{base}/{sid}/resend", headers=ctx["h"])).status_code == 200
    async with AsyncSessionLocal() as db:
        outs = (await db.scalars(select(EmailOutbox).where(EmailOutbox.to_email == email))).all()
        assert len(outs) == 2
    old_tok = sorted(outs, key=lambda e: e.created_at)[0].link.split("token=")[1]
    assert (await client.post("/auth/invitations/accept", json={"token": old_tok, "password": PW})).status_code == 400  # resend revoked it
    # other institution's officer cannot touch this record or list it
    assert (await client.post(f"{base}/{sid}/resend", headers=ctx["h_other"])).status_code == 404
    assert (await client.get(base, headers=ctx["h_other"])).status_code == 404
    assert (await client.post(f"{base}/{sid}/disable", headers=ctx["h"])).json()["status"] == "DISABLED"
    async with AsyncSessionLocal() as db:
        s = await db.get(InstitutionStudent, sid)
        assert s.status == "DISABLED"
    new_tok = sorted(outs, key=lambda e: e.created_at)[-1].link.split("token=")[1]
    assert (await client.post("/auth/invitations/accept", json={"token": new_tok, "password": PW})).status_code == 400  # disabled kills the link
    assert (await client.post(f"{base}/{sid}/enable", headers=ctx["h"])).json()["status"] == "PENDING"
    # claimed student: disable removes institution membership only, account still logs in
    r2 = await client.post(f"{base}/invite", headers=ctx["h"], json={"email": ctx["existing"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["action"] == "LINK_EXISTING_ACCOUNT"
    await client.post(f"{base}/{r2.json()['id']}/disable", headers=ctx["h"])
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == ctx["existing"]))
        p = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == u.id))
        assert p.institution_id is None and u.is_active
    assert (await client.post(f"{base}/{r2.json()['id']}/enable", headers=ctx["h"])).json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_students_and_recruiters_cannot_use_officer_endpoints(client, ctx):
    from tests.factories import make_company
    async with AsyncSessionLocal() as db:
        _, _, hc = await make_company(db, "NoAccess")
        _, _, hs = await make_student(db)
        await db.commit()
    base = f"/institutions/{ctx['iid']}/student-records"
    for h in (hc, hs):
        assert (await client.get(base, headers=h)).status_code == 403
        assert (await client.post(f"{base}/invite", headers=h, json={"email": "a@example.com"})).status_code == 403
        assert (await client.post(f"{base}/import/confirm", headers=h, files={"file": _csv([])})).status_code == 403
