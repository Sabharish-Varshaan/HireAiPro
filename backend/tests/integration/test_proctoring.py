"""Proctoring API: lifecycle, server-side gating, heartbeat-gap detection, event
dedupe, reviewer access and tenant isolation. No score/risk fields anywhere."""
import datetime as dt

import pytest

from app.api.v1 import proctoring as P
from app.core.database import AsyncSessionLocal
from app.models.enums import ApplicationStatus
from app.services.proctoring import service as svc
from tests.factories import make_application, make_company, make_institution, make_job, make_student
from tests.integration.test_candidate_pipeline import _published_assessment

OK = {"camera": True, "microphone": True, "audio_signal": True, "network": True, "fullscreen_capable": True, "browser": True}


@pytest.fixture
async def ctx():
    async with AsyncSessionLocal() as db:
        inst, _, hi = await make_institution(db, "PU")
        _, _, hi_other = await make_institution(db, "OtherU")
        org, rec, ha = await make_company(db, "A")
        org_b, rec_b, hb = await make_company(db, "B")
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        job_b = await make_job(db, org_b, rec_b, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db, institution=inst)
        app_ = await make_application(db, job, st, ApplicationStatus.APPLIED)
        await make_application(db, job_b, st, ApplicationStatus.APPLIED)
        a, _, _ = await _published_assessment(db, org, job)
        await db.commit()
    return dict(app=str(app_.id), assessment=str(a.id), hs=hs, ha=ha, hb=hb, hi=hi, hi_other=hi_other)


async def _ready_session(client, c):
    s = (await client.post("/proctoring/sessions", headers=c["hs"], json={"application_id": c["app"], "kind": "ASSESSMENT"})).json()
    assert (await client.post(f"/proctoring/sessions/{s['id']}/consent", headers=c["hs"])).json()["consented"]
    r = await client.post(f"/proctoring/sessions/{s['id']}/preflight", headers=c["hs"], json={"passed": True, "checks": OK})
    assert r.json()["preflight_status"] == "PASSED"
    assert (await client.post(f"/proctoring/sessions/{s['id']}/start", headers=c["hs"])).json()["session_status"] == "ACTIVE"
    return s["id"]


@pytest.mark.asyncio
async def test_system_check_requires_consent_and_every_required_device(client, ctx):
    s = (await client.post("/proctoring/sessions", headers=ctx["hs"], json={"application_id": ctx["app"], "kind": "ASSESSMENT"})).json()
    r = await client.post(f"/proctoring/sessions/{s['id']}/preflight", headers=ctx["hs"], json={"passed": True, "checks": OK})
    assert r.status_code == 409  # consent first
    await client.post(f"/proctoring/sessions/{s['id']}/consent", headers=ctx["hs"])
    r = await client.post(f"/proctoring/sessions/{s['id']}/preflight", headers=ctx["hs"],
                          json={"passed": True, "checks": {**OK, "microphone": False}})
    assert r.json()["preflight_status"] == "FAILED" and r.json()["missing"] == ["microphone"]
    assert (await client.post(f"/proctoring/sessions/{s['id']}/start", headers=ctx["hs"])).status_code == 409


@pytest.mark.asyncio
async def test_attempt_cannot_start_without_a_ready_session_when_enforced(client, ctx, monkeypatch):
    monkeypatch.setattr(P.settings, "PROCTOR_ENFORCE", True)
    body = {"application_id": ctx["app"]}
    r = await client.post(f"/assessments/{ctx['assessment']}/attempts", headers=ctx["hs"], json=body)
    assert r.status_code == 428 and r.json()["detail"]["code"] == "PROCTORING_REQUIRED"
    await _ready_session(client, ctx)
    assert (await client.post(f"/assessments/{ctx['assessment']}/attempts", headers=ctx["hs"], json=body)).status_code == 200


@pytest.mark.asyncio
async def test_events_dedupe_and_client_cannot_forge_server_events(client, ctx):
    sid = await _ready_session(client, ctx)
    t = dt.datetime.now(dt.timezone.utc)
    burst = [{"event_type": "TAB_HIDDEN", "occurred_at": (t + dt.timedelta(milliseconds=i * 100)).isoformat()} for i in range(5)]
    r = (await client.post(f"/proctoring/sessions/{sid}/events", headers=ctx["hs"], json={"events": burst})).json()
    assert r == {"stored": 1, "deduplicated": 4}
    later = [{"event_type": "TAB_VISIBLE", "occurred_at": (t + dt.timedelta(seconds=8)).isoformat(), "duration_ms": 8000},
             {"event_type": "FULLSCREEN_EXITED", "occurred_at": (t + dt.timedelta(seconds=9)).isoformat()}]
    assert (await client.post(f"/proctoring/sessions/{sid}/events", headers=ctx["hs"], json={"events": later})).json()["stored"] == 2
    forged = [{"event_type": "HEARTBEAT_RESTORED", "occurred_at": t.isoformat()}]
    assert (await client.post(f"/proctoring/sessions/{sid}/events", headers=ctx["hs"], json={"events": forged})).status_code == 422
    bogus = [{"event_type": "CHEATING_DETECTED", "occurred_at": t.isoformat()}]
    assert (await client.post(f"/proctoring/sessions/{sid}/events", headers=ctx["hs"], json={"events": bogus})).status_code == 422


@pytest.mark.asyncio
async def test_server_detects_heartbeat_gap(client, ctx, monkeypatch):
    sid = await _ready_session(client, ctx)
    assert (await client.post(f"/proctoring/sessions/{sid}/heartbeat", headers=ctx["hs"])).json()["restored_after_gap"] is False
    real_now = svc.now
    monkeypatch.setattr(svc, "now", lambda: real_now() + dt.timedelta(seconds=90))  # client silent for 90 s
    hb = (await client.post(f"/proctoring/sessions/{sid}/heartbeat", headers=ctx["hs"])).json()
    assert hb["restored_after_gap"] is True and hb["gap_seconds"] >= 89
    review = (await client.get(f"/proctoring/review/by-application/{ctx['app']}", headers=ctx["ha"])).json()
    types = [e["event_type"] for e in review["sessions"][0]["timeline"]]
    assert "HEARTBEAT_LOST" in types and "HEARTBEAT_RESTORED" in types
    restored = next(e for e in review["sessions"][0]["timeline"] if e["event_type"] == "HEARTBEAT_RESTORED")
    assert restored["source"] == "server" and restored["duration_ms"] >= 89000
    assert review["sessions"][0]["summary"]["heartbeat_interruptions"] == 1


@pytest.mark.asyncio
async def test_review_access_counts_and_no_automated_judgement(client, ctx):
    sid = await _ready_session(client, ctx)
    t = dt.datetime.now(dt.timezone.utc)
    await client.post(f"/proctoring/sessions/{sid}/events", headers=ctx["hs"], json={"events": [
        {"event_type": "FULLSCREEN_EXITED", "occurred_at": t.isoformat()},
        {"event_type": "TAB_HIDDEN", "occurred_at": (t + dt.timedelta(seconds=2)).isoformat()},
        {"event_type": "TAB_VISIBLE", "occurred_at": (t + dt.timedelta(seconds=10)).isoformat(), "duration_ms": 8000},
        {"event_type": "CAMERA_TRACK_ENDED", "occurred_at": (t + dt.timedelta(seconds=12)).isoformat()},
        {"event_type": "NETWORK_OFFLINE", "occurred_at": (t + dt.timedelta(seconds=20)).isoformat()},
        {"event_type": "NETWORK_ONLINE", "occurred_at": (t + dt.timedelta(seconds=33)).isoformat(), "duration_ms": 13000}]})
    await client.post(f"/proctoring/sessions/{sid}/complete", headers=ctx["hs"])
    for h in ("ha", "hi"):  # hiring company and enrolled institution
        r = await client.get(f"/proctoring/review/by-application/{ctx['app']}", headers=ctx[h])
        assert r.status_code == 200, h
        summ = r.json()["sessions"][0]["summary"]
        assert (summ["fullscreen_exits"], summ["tab_switches"], summ["camera_interruptions"], summ["network_outages"]) == (1, 1, 1, 1)
        assert summ["time_tab_hidden_ms"] == 8000 and summ["time_disconnected_ms"] == 13000
        assert not any(w in r.text.lower() for w in ("cheat", "risk", "suspicion", "integrity_score", "probability"))
    for h in ("hs", "hb", "hi_other"):  # student, other company, other institution
        assert (await client.get(f"/proctoring/review/by-application/{ctx['app']}", headers=ctx[h])).status_code in (403, 404), h


@pytest.mark.asyncio
async def test_student_cannot_touch_someone_elses_session(client, ctx):
    sid = await _ready_session(client, ctx)
    async with AsyncSessionLocal() as db:
        _, _, other = await make_student(db)
        await db.commit()
    assert (await client.post(f"/proctoring/sessions/{sid}/heartbeat", headers=other)).status_code == 404
    assert (await client.post(f"/proctoring/sessions/{sid}/events", headers=other, json={"events": []})).status_code == 404


@pytest.mark.asyncio
async def test_institution_lists_only_enrolled_students_applications(client, ctx):
    async with AsyncSessionLocal() as db:
        import uuid
        from app.models.applications import Application
        app_ = await db.get(Application, uuid.UUID(ctx["app"]))
        sid = app_.student_id
    me = (await client.get("/institutions/mine", headers=ctx["hi"])).json()
    inst_id = (me[0] if isinstance(me, list) else me)["id"]
    r = await client.get(f"/institutions/{inst_id}/students/{sid}/applications", headers=ctx["hi"])
    assert r.status_code == 200 and len(r.json()["applications"]) == 2
    assert (await client.get(f"/institutions/{inst_id}/students/{sid}/applications", headers=ctx["hi_other"])).status_code in (403, 404)
    assert (await client.get(f"/institutions/{inst_id}/students/{sid}/applications", headers=ctx["hs"])).status_code == 403


@pytest.mark.asyncio
async def test_concurrent_session_creates_resume_one_session(client, ctx):
    # smoke test: the in-process ASGI client does not reliably interleave requests,
    # so the row lock in create_session is the real guard
    import asyncio
    body = {"application_id": ctx["app"], "kind": "INTERVIEW"}
    rs = await asyncio.gather(*[client.post("/proctoring/sessions", headers=ctx["hs"], json=body) for _ in range(4)])
    assert len({r.json()["id"] for r in rs}) == 1
