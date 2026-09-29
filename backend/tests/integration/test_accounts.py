"""Account lifecycle: signup scope, invitations, password reset, disabled users."""

import datetime as dt

import pytest
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.security import verify_password
from app.models.accounts import EmailOutbox, InstitutionStudent, Invitation, PasswordReset
from app.models.institutions import Institution, InstitutionMember
from app.models.organizations import Organization, OrganizationMember
from app.models.students import StudentProfile
from app.models.users import User
from app.services.accounts import service as acct
from tests.factories import uniq

PW = "Correct-horse-9"


async def _link_from_outbox(email: str) -> str:
    async with AsyncSessionLocal() as db:
        e = (await db.scalars(select(EmailOutbox).where(EmailOutbox.to_email == email)
                              .order_by(EmailOutbox.created_at.desc()))).first()
        return e.link


def _token(link: str) -> str:
    return link.split("token=")[1]


@pytest.mark.asyncio
async def test_signup_scope_and_ownership_rows(client):
    for role in ("INSTITUTION_ADMIN", "FACULTY", "DEPARTMENT_HEAD", "PLATFORM_ADMIN", "COMPANY_ADMIN"):
        r = await client.post("/auth/signup", json={"email": f"{uniq('x')}@example.com", "password": PW, "full_name": "X", "role": role})
        assert r.status_code == 400, role
    e = f"{uniq('po')}@example.com"
    assert (await client.post("/auth/signup", json={"email": e, "password": PW, "full_name": "PO", "role": "PLACEMENT_OFFICER"})).status_code == 400  # needs institution
    r = await client.post("/auth/signup", json={"email": e, "password": PW, "full_name": "PO", "role": "PLACEMENT_OFFICER",
                                                "institution_name": "Verity Institute"})
    assert r.status_code == 200 and r.json()["role"] == "PLACEMENT_OFFICER"
    e2 = f"{uniq('rc')}@example.com"
    assert (await client.post("/auth/signup", json={"email": e2, "password": PW, "full_name": "R", "role": "RECRUITER"})).status_code == 400
    assert (await client.post("/auth/signup", json={"email": e2, "password": PW, "full_name": "R", "role": "RECRUITER",
                                                    "company_name": "Acme Hire"})).status_code == 200
    async with AsyncSessionLocal() as db:
        po = await db.scalar(select(User).where(User.email == e))
        assert po.password_hash != PW and po.password_hash.startswith("$argon2")
        inst = await db.scalar(select(Institution).where(Institution.created_by_user_id == po.id))
        assert inst.name == "Verity Institute"
        assert await db.scalar(select(InstitutionMember).where(InstitutionMember.user_id == po.id, InstitutionMember.role == "PLACEMENT_OFFICER"))
        rc = await db.scalar(select(User).where(User.email == e2))
        assert await db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == rc.id))


async def _student_invite(email="stu"):
    async with AsyncSessionLocal() as db:
        from tests.factories import make_institution
        inst, po, _ = await make_institution(db, "InvU")
        s = InstitutionStudent(institution_id=inst.id, email=f"{uniq(email)}@example.com", first_name="Ada", last_name="Lovelace", status="PENDING")
        db.add(s)
        await db.flush()
        from app.models.enums import UserRole
        await acct.create_invitation(db, email=s.email, role=UserRole.STUDENT, created_by=po.id, institution_id=inst.id,
                                     institution_student_id=s.id, subject="Join", intro="hi")
        await db.commit()
        return s.email, inst.id


@pytest.mark.asyncio
async def test_invitation_claim_is_single_use_hashed_and_activates(client):
    email, inst_id = await _student_invite()
    link = await _link_from_outbox(email)
    raw = _token(link)
    async with AsyncSessionLocal() as db:
        inv = await db.scalar(select(Invitation).where(Invitation.email == email))
        assert raw not in (inv.token_hash, ) and inv.token_hash == acct.hash_token(raw) and len(raw) >= 40
    info = await client.get(f"/auth/invitations/{raw}")
    assert info.status_code == 200 and info.json()["email"] == email and info.json()["full_name"] == "Ada Lovelace"
    assert (await client.get("/auth/invitations/not-a-real-token")).status_code == 410
    assert (await client.post("/auth/invitations/accept", json={"token": raw, "password": "short"})).status_code == 400
    ok = await client.post("/auth/invitations/accept", json={"token": raw, "password": PW})
    assert ok.status_code == 200 and ok.json()["role"] == "STUDENT"
    again = await client.post("/auth/invitations/accept", json={"token": raw, "password": "Another-pass-1"})
    assert again.status_code == 400  # reuse rejected
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert verify_password(PW, u.password_hash)
        p = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == u.id))
        assert p.institution_id == inst_id
        assert (await db.scalar(select(InstitutionStudent).where(InstitutionStudent.email == email))).status == "ACTIVE"
    assert (await client.post("/auth/login", json={"email": email, "password": PW})).status_code == 200
    assert (await client.post("/auth/login", json={"email": email, "password": "wrong-password"})).status_code == 401


@pytest.mark.asyncio
async def test_expired_and_resent_invitations_are_rejected(client):
    email, _ = await _student_invite()
    raw = _token(await _link_from_outbox(email))
    async with AsyncSessionLocal() as db:
        await db.execute(update(Invitation).where(Invitation.email == email).values(expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)))
        await db.commit()
    assert (await client.post("/auth/invitations/accept", json={"token": raw, "password": PW})).status_code == 400
    assert (await client.get(f"/auth/invitations/{raw}")).status_code == 410
    # resend: new invitation revokes the old one
    email2, _ = await _student_invite("stu2")
    old = _token(await _link_from_outbox(email2))
    async with AsyncSessionLocal() as db:
        from app.models.enums import UserRole
        s = await db.scalar(select(InstitutionStudent).where(InstitutionStudent.email == email2))
        await acct.create_invitation(db, email=email2, role=UserRole.STUDENT, created_by=None, institution_id=s.institution_id,
                                     institution_student_id=s.id, subject="Join again", intro="hi")
        await db.commit()
    new = _token(await _link_from_outbox(email2))
    assert new != old
    assert (await client.post("/auth/invitations/accept", json={"token": old, "password": PW})).status_code == 400
    assert (await client.post("/auth/invitations/accept", json={"token": new, "password": PW})).status_code == 200


@pytest.mark.asyncio
async def test_password_reset_flow(client):
    email = f"{uniq('rs')}@example.com"
    await client.post("/auth/signup", json={"email": email, "password": PW, "full_name": "S", "role": "STUDENT"})
    unknown = await client.post("/auth/password/forgot", json={"email": f"{uniq('nobody')}@example.com"})
    known = await client.post("/auth/password/forgot", json={"email": email})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()  # no enumeration
    raw = _token(await _link_from_outbox(email))
    async with AsyncSessionLocal() as db:
        pr = await db.scalar(select(PasswordReset).where(PasswordReset.token_hash == acct.hash_token(raw)))
        assert pr is not None
    assert (await client.post("/auth/password/reset", json={"token": raw, "password": "New-password-77"})).status_code == 200
    assert (await client.post("/auth/password/reset", json={"token": raw, "password": "Third-password-8"})).status_code == 400
    assert (await client.post("/auth/login", json={"email": email, "password": PW})).status_code == 401
    assert (await client.post("/auth/login", json={"email": email, "password": "New-password-77"})).status_code == 200


@pytest.mark.asyncio
async def test_disabled_account_denied_even_with_existing_token(client):
    email = f"{uniq('dis')}@example.com"
    tok = (await client.post("/auth/signup", json={"email": email, "password": PW, "full_name": "D", "role": "STUDENT"})).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/auth/me", headers=h)).status_code == 200
    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_active=False))
        await db.commit()
    assert (await client.get("/auth/me", headers=h)).status_code == 401
    assert (await client.post("/auth/login", json={"email": email, "password": PW})).status_code == 401
    forgot = await client.post("/auth/password/forgot", json={"email": email})
    assert forgot.status_code == 202
    async with AsyncSessionLocal() as db:  # disabled users get no reset mail
        assert not (await db.scalars(select(EmailOutbox).where(EmailOutbox.to_email == email))).first()


@pytest.mark.asyncio
async def test_outbox_hidden_outside_dev(client, monkeypatch):
    assert (await client.get("/dev/email-outbox")).status_code == 200
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "APP_ENV", "production")
    assert (await client.get("/dev/email-outbox")).status_code == 404
    async with AsyncSessionLocal() as db:
        n = len((await db.scalars(select(EmailOutbox))).all())
        await acct.send_email(db, "x@example.com", "s", "b")
        await db.commit()
        assert len((await db.scalars(select(EmailOutbox))).all()) == n  # production writes nothing
