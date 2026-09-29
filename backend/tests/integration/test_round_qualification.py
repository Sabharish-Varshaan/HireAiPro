"""Deterministic round qualification end to end: thresholds, locked next rounds, override + audit, pending evaluation, versioning."""
import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.applications import Application
from app.models.enums import JobStatus
from app.models.interviews import Interview, InterviewTurn
from app.models.misc import AgentRun, AuditEvent
from app.models.pipeline import ApplicationStageProgress, HiringStage, RoundResult
from app.services.pipeline import qualification as Q
from app.services.pipeline import service as pl
from app.services.pipeline import stages as S
from tests.factories import configure_pipeline, make_application, make_company, make_job, make_stage_assessment, make_student
from tests.integration.test_hiring_pipeline import SKILLS


async def _take(client, hs, assessment_id, app_id, correct: int, total: int):
    """Take an assessment through the API, answering `correct` of `total` MCQs right (option 1 is the key)."""
    att = (await client.post(f"/assessments/{assessment_id}/attempts", headers=hs, json={"application_id": app_id})).json()["id"]
    qs = [q for s in (await client.get(f"/assessments/attempts/{att}", headers=hs)).json()["sections"] for q in s["questions"]]
    for i, q in enumerate(qs):
        await client.put(f"/assessments/attempts/{att}/answers", headers=hs, json={"assessment_question_id": q["id"], "selected_option_index": 1 if i < correct else 0})
    assert (await client.post(f"/assessments/attempts/{att}/submit", headers=hs)).json()["completed"]
    return att


async def _world(name, thresholds: dict, n_apt=25, n_tech=3):
    async with AsyncSessionLocal() as db:
        org, rec, hc = await make_company(db, name)
        job = await make_job(db, org, rec, SKILLS, status=JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.APTITUDE, S.TECHNICAL, S.CODING])
        a = await make_stage_assessment(db, org, job, S.APTITUDE, n=n_apt)
        t = await make_stage_assessment(db, org, job, S.TECHNICAL, n=n_tech, mcq_only=True)
        c = await make_stage_assessment(db, org, job, S.CODING)
        for st, key in ((a[0], S.APTITUDE), (t[0], S.TECHNICAL), (c[0], S.CODING)):
            th = thresholds.get(key)
            st.pass_threshold, st.auto_qualify = th, th is not None
        stu, _, hs = await make_student(db)
        app_ = await make_application(db, job, stu)
        await db.commit()
        return dict(job=job, hc=hc, hs=hs, app=str(app_.id), apt=str(a[1].id), tech=str(t[1].id), code=str(c[1].id), rec=rec)


def _round(j, stage_type):
    return next(s for s in j["stages"] if s["stage_type"] == stage_type)


@pytest.mark.asyncio
async def test_three_round_scenario_above_below_threshold_locked_next_round_and_override(client):
    w = await _world("QualCo", {S.APTITUDE: 60, S.TECHNICAL: 70, S.CODING: 65})
    journey = lambda h: client.get(f"/hiring-pipeline/applications/{w['app']}", headers=h)

    # Round 1: 18 of 25 = 72 >= 60 -> qualified -> round 2 unlocks (available, not started: no timer runs)
    await _take(client, w["hs"], w["apt"], w["app"], 18, 25)
    s = (await journey(w["hs"])).json()
    r1 = _round(s, S.APTITUDE)["round"]
    assert (r1["score"], r1["threshold"], r1["decision"], r1["result_label"], r1["next"]) == (72.0, 60.0, "QUALIFIED", "Qualified for the next round", "Technical Assessment")
    assert [x["status"] for x in s["stages"]] == ["COMPLETED", "AVAILABLE", "LOCKED"]
    assert "reason" not in r1 and "components" not in r1 and "automatic_decision" not in r1  # no internals for the candidate
    # Round 3 cannot be opened before qualifying for round 2 (server-side)
    locked = await client.post(f"/assessments/{w['code']}/attempts", headers=w["hs"], json={"application_id": w["app"]})
    assert locked.status_code == 409 and locked.json()["detail"]["code"] == "STAGE_LOCKED"

    # Round 2: 2 of 3 = 66.7 < 70 -> not qualified -> round 3 stays locked; a human reviews
    await _take(client, w["hs"], w["tech"], w["app"], 2, 3)
    s = (await journey(w["hs"])).json()
    r2 = _round(s, S.TECHNICAL)["round"]
    assert (r2["score"], r2["threshold"], r2["decision"], r2["result_label"], r2["next"]) == (66.7, 70.0, "NOT_QUALIFIED", "Round completed", None)
    assert [x["status"] for x in s["stages"]] == ["COMPLETED", "COMPLETED", "LOCKED"] and s["status"].endswith("UNDER_REVIEW")
    still = await client.post(f"/assessments/{w['code']}/attempts", headers=w["hs"], json={"application_id": w["app"]})
    assert still.status_code == 409 and still.json()["detail"]["code"] == "STAGE_LOCKED"

    # Company sees the full record; a student cannot override
    cj = (await journey(w["hc"])).json()
    c2 = _round(cj, S.TECHNICAL)["round"]
    assert c2["automatic_decision"] == "NOT_QUALIFIED" and c2["reason"] == "below_threshold" and c2["override"] is None and c2["evaluation_version"] == 1
    assert c2["components"]["mcq"]["score"] == 66.7 and _round(cj, S.TECHNICAL)["pass_threshold"] == 70.0
    denied = await client.post(f"/hiring-pipeline/applications/{w['app']}/stages/{S.TECHNICAL}/override", headers=w["hs"], json={"decision": "ADVANCE", "reason": "please let me"})
    assert denied.status_code == 403

    # Override: a reason is mandatory; score/threshold/automatic decision never change; audited; next round unlocks
    url = f"/hiring-pipeline/applications/{w['app']}/stages/{S.TECHNICAL}/override"
    assert (await client.post(url, headers=w["hc"], json={"decision": "ADVANCE", "reason": " "})).status_code == 409
    ok = await client.post(url, headers=w["hc"], json={"decision": "ADVANCE", "reason": "Strong portfolio evidence"})
    assert ok.status_code == 200, ok.text
    o = ok.json()
    assert (o["score"], o["threshold"], o["automatic_decision"], o["decision"]) == (66.7, 70.0, "NOT_QUALIFIED", "QUALIFIED")
    assert o["override"]["decision"] == "ADVANCED" and o["override"]["reason"] == "Strong portfolio evidence" and o["override"]["previous"] == "NOT_QUALIFIED" and o["override"]["at"]
    s = (await journey(w["hs"])).json()
    assert [x["status"] for x in s["stages"]] == ["COMPLETED", "COMPLETED", "AVAILABLE"] and s["status"].endswith("ASSESSMENT_PENDING")
    assert (await client.post(url, headers=w["hc"], json={"decision": "ADVANCE", "reason": "again, for good measure"})).status_code == 409  # already advancing
    async with AsyncSessionLocal() as db:
        rr = (await db.scalars(select(RoundResult).join(HiringStage, HiringStage.id == RoundResult.hiring_stage_id)
                               .where(RoundResult.application_id == w["app"], HiringStage.stage_type == S.TECHNICAL))).one()
        assert rr.score == 66.7 and rr.threshold == 70.0 and rr.decision == "NOT_QUALIFIED" and rr.override_by is not None  # original result untouched
        ev = (await db.scalars(select(AuditEvent).where(AuditEvent.action == "round_override", AuditEvent.entity_id == rr.id))).one()
        assert ev.event_metadata["previous"] == "NOT_QUALIFIED" and ev.event_metadata["new"] == "QUALIFIED" and ev.event_metadata["reason"] == "Strong portfolio evidence"
    # round 3 can now start
    assert (await client.post(f"/assessments/{w['code']}/attempts", headers=w["hs"], json={"application_id": w["app"]})).status_code == 200

    # A HOLD after the next round has started is refused
    held = await client.post(url, headers=w["hc"], json={"decision": "HOLD", "reason": "second thoughts here"})
    assert held.status_code == 409


@pytest.mark.asyncio
async def test_a_score_exactly_at_the_threshold_qualifies(client):
    w = await _world("EdgeCo", {S.APTITUDE: 75}, n_apt=4)
    await _take(client, w["hs"], w["apt"], w["app"], 3, 4)  # 75.0 == 75.0
    r = _round((await client.get(f"/hiring-pipeline/applications/{w['app']}", headers=w["hs"])).json(), S.APTITUDE)["round"]
    assert (r["score"], r["threshold"], r["decision"]) == (75.0, 75.0, "QUALIFIED")


@pytest.mark.asyncio
async def test_thresholds_are_versioned_history_is_not_recalculated_and_reevaluation_is_explicit(client):
    w = await _world("VerCo", {S.APTITUDE: 60})
    await _take(client, w["hs"], w["apt"], w["app"], 18, 25)  # 72, judged against 60
    body = {"stages": [{"stage_type": S.APTITUDE, "pass_threshold": 75, "auto_qualify": True}]}
    assert (await client.put(f"/hiring-pipeline/jobs/{w['job'].id}", headers=w["hc"], json={"stages": [{"stage_type": S.TECHNICAL, "enabled": True}]})).status_code == 409  # content is frozen
    assert (await client.put(f"/hiring-pipeline/jobs/{w['job'].id}/qualification", headers=w["hc"], json=body)).status_code == 200  # thresholds are not
    cj = (await client.get(f"/hiring-pipeline/applications/{w['app']}", headers=w["hc"])).json()
    r = _round(cj, S.APTITUDE)
    assert r["pass_threshold"] == 75.0 and r["round"]["threshold"] == 60.0 and r["round"]["decision"] == "QUALIFIED"  # the earlier candidate keeps the threshold used
    ev = await client.post(f"/hiring-pipeline/applications/{w['app']}/stages/{S.APTITUDE}/evaluate", headers=w["hc"])
    assert ev.status_code == 200 and ev.json()["threshold"] == 75.0 and ev.json()["decision"] == "NOT_QUALIFIED" and ev.json()["evaluation_version"] == 2
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(RoundResult).where(RoundResult.application_id == w["app"]).order_by(RoundResult.evaluation_version))).all()
        assert [(x.evaluation_version, x.threshold, x.decision) for x in rows] == [(1, 60.0, "QUALIFIED"), (2, 75.0, "NOT_QUALIFIED")]  # both kept
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "round_reevaluated")) >= 1


@pytest.mark.asyncio
async def test_threshold_and_weight_settings_are_validated_by_the_server(client):
    w = await _world("CfgCo", {})
    def put(stage):  # settings are editable on a published job through their own endpoint (content is frozen)
        return client.put(f"/hiring-pipeline/jobs/{w['job'].id}/qualification", headers=w["hc"], json={"stages": [{"stage_type": S.TECHNICAL, **stage}]})
    for bad in ({"pass_threshold": -1}, {"pass_threshold": 101}, {"auto_qualify": True}, {"pass_threshold": 70, "weights": {"mcq": 40, "written": 40}},
                {"pass_threshold": 70, "weights": {"coding": 100}}):
        assert (await put(bad)).status_code == 422, bad
    async with AsyncSessionLocal() as db:  # HR: enable it on the (still published) job's pipeline row so the endpoint can judge the request
        (await db.scalar(select(HiringStage).where(HiringStage.job_id == w["job"].id, HiringStage.stage_type == S.HR_INTERVIEW))).enabled = True
        await db.commit()
    hr = await client.put(f"/hiring-pipeline/jobs/{w['job'].id}/qualification", headers=w["hc"], json={"stages": [{"stage_type": S.HR_INTERVIEW, "pass_threshold": 50}]})
    assert hr.status_code == 422
    ok = await put({"pass_threshold": 70, "auto_qualify": True, "weights": {"mcq": 40, "written": 60}})
    assert ok.status_code == 200
    tech = next(s for s in ok.json()["stages"] if s["stage_type"] == S.TECHNICAL)
    assert (tech["pass_threshold"], tech["auto_qualify"], tech["weights"]) == (70.0, True, {"mcq": 40.0, "written": 60.0})
    assert tech["weight_components"] == ["mcq", "written"]


@pytest.mark.asyncio
async def test_a_missing_weighted_component_gives_manual_review_not_a_misleading_score(client):
    w = await _world("MissCo", {S.TECHNICAL: 60})
    async with AsyncSessionLocal() as db:
        st = await db.scalar(select(HiringStage).where(HiringStage.job_id == w["job"].id, HiringStage.stage_type == S.TECHNICAL))
        st.weights = {"mcq": 20, "written": 80}  # this stage only has MCQs
        ap = await db.scalar(select(ApplicationStageProgress).join(HiringStage, HiringStage.id == ApplicationStageProgress.hiring_stage_id)
                             .where(ApplicationStageProgress.application_id == w["app"], HiringStage.stage_type == S.APTITUDE))
        await db.commit()
    await _take(client, w["hs"], w["apt"], w["app"], 20, 25)
    await _take(client, w["hs"], w["tech"], w["app"], 3, 3)
    r = _round((await client.get(f"/hiring-pipeline/applications/{w['app']}", headers=w["hc"])).json(), S.TECHNICAL)["round"]
    assert r["score"] is None and r["decision"] == "MANUAL_REVIEW" and r["reason"].startswith("missing_component")
    s = (await client.get(f"/hiring-pipeline/applications/{w['app']}", headers=w["hs"])).json()
    assert _round(s, S.CODING)["status"] == "LOCKED"  # nobody advances on a number that was never computed


@pytest.mark.asyncio
async def test_pending_evaluation_decides_nothing_and_a_late_score_completes_it(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc = await make_company(db, "PendCo")
        job = await make_job(db, org, rec, SKILLS, status=JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.TECH_INTERVIEW, S.HR_INTERVIEW])
        ti = await db.scalar(select(HiringStage).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.TECH_INTERVIEW))
        ti.pass_threshold, ti.auto_qualify = 60, True
        stu, _, hs = await make_student(db)
        app_ = await make_application(db, job, stu)
        from tests.factories import skill

        py = await skill(db, "Python")
        itv = Interview(application_id=app_.id, student_id=stu.id, job_id=job.id, stage_type=S.TECH_INTERVIEW, hiring_stage_id=ti.id, max_turns=2, status="COMPLETED")
        db.add(itv)
        await db.flush()
        turns = [InterviewTurn(interview_id=itv.id, turn_index=i, target_skill_id=py.id, question_text=f"Q{i} about python internals?", student_answer_text="an answer")
                 for i in range(2)]
        db.add_all(turns)
        await pl.ensure_progress(db, app_)
        await db.flush()
        await pl.mark_started(db, app_, ti, stu.user_id)
        await pl.complete_stage(db, app_, ti, stu.user_id)  # scoring has not finished (provider slow or failed)
        await db.commit()
        app_id = app_.id
    async with AsyncSessionLocal() as db:
        rr = await Q.latest_result(db, app_id, ti.id)
        assert rr.decision == Q.PENDING and rr.score is None  # no decision; not a failure
        rows = {s.stage_type: p.status for s, p in await pl.progress_rows(db, app_id)}
        assert rows == {S.TECH_INTERVIEW: "COMPLETED", S.HR_INTERVIEW: "LOCKED"}
        assert str((await db.get(Application, app_id)).status).endswith(("INTERVIEW_PENDING", "ASSESSMENT_PENDING", "APPLIED"))  # not sent to review
        for t in (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == itv.id))).all():  # the scores arrive
            t.rubric_evaluation = {"concept_accuracy": 0.8, "reasoning": 0.7, "completeness": 0.7, "communication": 0.9, "evaluator_confidence": 0.9}
        await db.commit()
    async with AsyncSessionLocal() as db:
        await pl.finalize_pending(db, app_id)
        await db.commit()
    async with AsyncSessionLocal() as db:
        rr = await Q.latest_result(db, app_id, ti.id)
        assert rr.decision == Q.QUALIFIED and rr.evaluation_version == 1 and rr.score == pytest.approx(76.0)  # 0.40*80 + 0.25*70 + 0.25*70 + 0.10*90
        assert {s.stage_type: p.status for s, p in await pl.progress_rows(db, app_id)}[S.HR_INTERVIEW] == "AVAILABLE"


@pytest.mark.asyncio
async def test_mcq_scoring_calls_no_model_and_leaves_a_compact_trace(client, monkeypatch):
    from app.api.v1 import assessments as api

    class Boom:
        def __getattr__(self, n):
            raise AssertionError("an MCQ-only attempt must not call a model")
    monkeypatch.setattr(api, "get_ai_gateway", lambda: Boom())
    w = await _world("TraceCo", {S.APTITUDE: 50}, n_apt=4)
    att = await _take(client, w["hs"], w["apt"], w["app"], 3, 4)
    async with AsyncSessionLocal() as db:
        run = (await db.scalars(select(AgentRun).where(AgentRun.agent_type == "orchestrator", AgentRun.context_id == att))).one()
        assert run.task == "score_assessment" and [c["agent"] for c in run.tool_calls if "agent" in c] == ["mcq_checker"]
        skipped = next(c for c in run.tool_calls if "skipped" in c)
        assert "assessment_evaluator" in skipped["skipped"] and "deterministic" in " ".join(skipped["notes"])
        assert "reasoning" not in str(run.tool_calls)  # no chain of thought is stored
