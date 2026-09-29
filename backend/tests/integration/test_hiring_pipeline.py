"""Job-specific hiring pipeline: configuration, deterministic progression, separate timers/versions, the deep technical interview,
the separate HR interview, role visibility and tenant isolation."""
import datetime as dt
import time
import uuid

import pytest
from sqlalchemy import func, select

from app.api.v1 import interviews as iv_api
from app.core.database import AsyncSessionLocal
from app.models.applications import Application
from app.models.assessments import AssessmentAttempt, AssessmentQuestion
from app.models.enums import ApplicationStatus, JobStatus, QuestionSourceType, QuestionStatus, QuestionType, Visibility
from app.models.evidence import SkillEvidence
from app.models.interviews import Interview, InterviewPoolQuestion, InterviewTurn
from app.models.pipeline import ApplicationStageProgress, HiringStage
from app.models.questions import Question
from app.schemas.rubric import RubricEvaluation
from app.services.interviews import pool as P
from app.services.pipeline import stages as S
from tests.factories import (configure_pipeline, make_application, make_company, make_institution, make_job, make_stage_assessment, make_student, skill)

SKILLS = [("Python", "required", 0.6, 1.0), ("PostgreSQL", "required", 0.6, 0.8), ("Git", "preferred", 0.4, 0.5)]


def stage_cfg(t, **over):
    base = {"stage_type": t, "enabled": True, "required": True, "proctored": True}
    return {**base, **over}


class FakeGW:
    """Pool/aptitude generation without a model. Records every prompt so isolation tests can inspect them."""

    def __init__(self):
        self.prompts: list[str] = []
        self.n = 0

    async def generate_structured(self, prompt, schema, **kw):
        self.prompts.append(prompt)
        self.n += 1
        if schema is P._PoolBatch:
            layers = [int(x.split()[1].rstrip(":")) for x in prompt.splitlines() if x.strip().startswith("layer ")]
            return P._PoolBatch(questions=[P._PQ(layer=layer, question_text=f"Interview question {self.n}-{layer}-{i} about the competency at layer {layer}, please explain.",
                                                 reason_for_question="depth") for layer in layers for i in (1, 2)])
        if schema is P._HRBatch:
            return P._HRBatch(questions=[P._HRQ(category="motivation", question_text="Do you have any medical conditions we should know about?"),
                                         P._HRQ(category="work preferences", question_text="How do you like to plan a week that has several deadlines?")])
        from app.services.pipeline import stage_content as SC

        if schema is SC._AptQ:
            return SC._AptQ(question_text=f"Generated aptitude question {self.n}: what is {self.n} plus 4?", options=[str(self.n + 3), str(self.n + 4), str(self.n + 5), "0"],
                            correct_option_index=1)
        if schema is SC._Solve:
            return SC._Solve(answer_index=1)
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def gw(monkeypatch):
    g = FakeGW()
    from app.services.pipeline import stage_content as SC

    monkeypatch.setattr(P, "get_ai_gateway", lambda: g)
    monkeypatch.setattr(SC, "get_ai_gateway", lambda: g)
    monkeypatch.setattr(P, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(P, "to_source_refs", lambda docs: [])
    return g


async def _company(db, name="PipeCo", status=JobStatus.REQUIREMENTS_CONFIRMED):
    org, rec, hc = await make_company(db, name)
    job = await make_job(db, org, rec, SKILLS, status=status)
    job.employment_type, job.work_mode = "FULL_TIME", "REMOTE"
    return org, rec, hc, job


# ------------------------------------------------------------------ configuration
@pytest.mark.asyncio
async def test_default_pipeline_matches_legacy_behaviour_and_can_be_reconfigured(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db)
        _, _, other = await make_company(db, "OtherPipeCo")
        _, _, hs = await make_student(db)
        await db.commit()
    v = (await client.get(f"/hiring-pipeline/jobs/{job.id}", headers=hc)).json()
    on = [s["stage_type"] for s in v["stages"] if s["enabled"]]
    assert on == [S.TECHNICAL, S.TECH_INTERVIEW] and [s["label"] for s in v["stages"]][:2] == ["Aptitude Assessment", "Technical Assessment"]
    assert all("_" not in s["label"] for s in v["stages"]) and v["issues"]  # nothing generated yet -> publishing is blocked with reasons

    body = {"stages": [stage_cfg(S.APTITUDE, question_count=10, duration_minutes=30),
                       stage_cfg(S.TECHNICAL, question_count=12, duration_minutes=40, config={"mcq_share": 50}),
                       stage_cfg(S.CODING, question_count=2, duration_minutes=60, config={"languages": ["python", "cpp"], "difficulty": "hard"}),
                       stage_cfg(S.TECH_INTERVIEW, duration_minutes=60, config={"min_questions": 6, "max_questions": 10}),
                       stage_cfg(S.HR_INTERVIEW, duration_minutes=20, config={"categories": ["communication", "motivation", "availability and logistics"]})]}
    r = await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json=body)
    assert r.status_code == 200, r.text
    got = {s["stage_type"]: s for s in r.json()["stages"]}
    assert all(s["enabled"] for s in got.values()) and got[S.CODING]["config"]["languages"] == ["cpp", "python"] and got[S.CODING]["duration_minutes"] == 60

    # reorder inside the assessment group, disable a stage
    body["stages"] = [body["stages"][2], body["stages"][1], {**body["stages"][0], "enabled": False}, body["stages"][3], body["stages"][4]]
    r = await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json=body)
    assert r.status_code == 200
    order = [(s["stage_type"], s["enabled"]) for s in r.json()["stages"]]
    assert order[:3] == [(S.CODING, True), (S.TECHNICAL, True), (S.APTITUDE, False)]

    # nonsense orders and settings are refused
    bad = {"stages": [stage_cfg(S.HR_INTERVIEW), stage_cfg(S.TECHNICAL)]}
    assert (await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json=bad)).status_code == 422
    for cfg in ({"stage_type": S.APTITUDE, "config": {"categories": {"Verbal Ability": 60}}},
                {"stage_type": S.CODING, "config": {"languages": ["cobol"]}},
                {"stage_type": S.HR_INTERVIEW, "config": {"categories": ["religion"]}},
                {"stage_type": S.TECHNICAL, "config": {"mcq_share": 130}}, {"stage_type": "MAGIC"}):
        assert (await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json={"stages": [{**stage_cfg(cfg["stage_type"]), **cfg}]})).status_code == 422, cfg
    assert (await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json={"stages": [stage_cfg(S.TECHNICAL, enabled=False)]})).status_code == 422  # nothing enabled

    assert (await client.get(f"/hiring-pipeline/jobs/{job.id}", headers=other)).status_code in (403, 404)  # another company
    assert (await client.get(f"/hiring-pipeline/jobs/{job.id}", headers=hs)).status_code == 403  # students do not see the configuration
    assert (await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=other, json=body)).status_code in (403, 404)


@pytest.mark.asyncio
async def test_publish_is_validated_per_enabled_stage_and_then_freezes_everything(client, gw):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "PubCo")
        await configure_pipeline(db, job, [S.APTITUDE, S.TECHNICAL], {S.APTITUDE: 20})  # HR and coding are disabled: not validated
        await make_stage_assessment(db, org, job, S.TECHNICAL, published=False)
        apt_stage = (await db.scalar(select(HiringStage).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.APTITUDE)))
        apt_stage.assessment_id = None
        await db.commit()
    # aptitude is enabled but empty -> blocked with a useful message; disabled HR / coding say nothing
    r = await client.post(f"/hiring-pipeline/jobs/{job.id}/publish", headers=hc)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PIPELINE_INCOMPLETE"
    issues = r.json()["detail"]["issues"]
    assert [i["stage_type"] for i in issues] == [S.APTITUDE] and "no questions" in issues[0]["message"] and "Aptitude Assessment" in issues[0]["message"]
    # a technical interview without a competency blueprint is blocked too
    async with AsyncSessionLocal() as db:
        from app.models.jobs import Job, JobSkill

        await configure_pipeline(db, await db.get(Job, job.id), [S.TECHNICAL, S.TECH_INTERVIEW])

        for js in (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all():
            js.confirmed = False
        await db.commit()
    r = await client.post(f"/hiring-pipeline/jobs/{job.id}/publish", headers=hc)
    assert r.status_code == 409 and any(i["stage_type"] == S.TECH_INTERVIEW and "blueprint" in i["message"] for i in r.json()["detail"]["issues"])
    async with AsyncSessionLocal() as db:
        from app.models.jobs import JobSkill

        for js in (await db.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all():
            js.confirmed = True
        await db.commit()
    kicked = []
    from app.api.v1 import interviews as api

    api_kick = api._kick_prepare
    api._kick_prepare = lambda job_id, stage_type="TECHNICAL_INTERVIEW": kicked.append(stage_type)
    try:
        ok = await client.post(f"/hiring-pipeline/jobs/{job.id}/publish", headers=hc)
    finally:
        api._kick_prepare = api_kick
    assert ok.status_code == 200, ok.text
    assert kicked == [S.TECH_INTERVIEW] and ok.json()["published"] and all(s["status"] == "PUBLISHED" for s in ok.json()["stages"] if s["enabled"])
    async with AsyncSessionLocal() as db:
        from app.models.assessments import Assessment, AssessmentVersion

        a = await db.get(Assessment, (await db.scalar(select(HiringStage.assessment_id).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.TECHNICAL))))
        assert a.status == "PUBLISHED" and await db.scalar(select(func.count()).select_from(AssessmentVersion).where(AssessmentVersion.assessment_id == a.id)) == 1
        from app.models.jobs import Job

        assert (await db.get(Job, job.id)).status == JobStatus.PUBLISHED
    # frozen: no more reconfiguration or regeneration, no second publish
    assert (await client.put(f"/hiring-pipeline/jobs/{job.id}", headers=hc, json={"stages": [stage_cfg(S.TECHNICAL)]})).status_code == 409
    assert (await client.post(f"/hiring-pipeline/jobs/{job.id}/publish", headers=hc)).status_code == 409
    assert (await client.post(f"/hiring-pipeline/jobs/{job.id}/stages/{S.TECHNICAL}/generate", headers=hc)).status_code == 409


# ------------------------------------------------------------------ progression, timers, versions
async def _start(client, hs, a, app_):
    return await client.post(f"/assessments/{a}/attempts", headers=hs, json={"application_id": app_})


@pytest.mark.asyncio
async def test_stages_unlock_in_order_each_with_its_own_timer_and_version(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "SeqCo", JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.APTITUDE, S.TECHNICAL, S.CODING], {S.APTITUDE: 20, S.TECHNICAL: 35, S.CODING: 50})
        made = {t: (await make_stage_assessment(db, org, job, t, duration=d)) for t, d in ((S.APTITUDE, 20), (S.TECHNICAL, 35), (S.CODING, 50))}
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        await db.commit()
    aid = {t: str(made[t][1].id) for t in made}
    app_id = str(app_.id)
    journey = lambda h: client.get(f"/hiring-pipeline/applications/{app_id}", headers=h)

    j = (await journey(hs)).json()
    assert [(s["label"], s["status"]) for s in j["stages"]] == [("Aptitude Assessment", "AVAILABLE"), ("Technical Assessment", "LOCKED"), ("Coding Assessment", "LOCKED")]
    locked = await _start(client, hs, aid[S.TECHNICAL], app_id)
    assert locked.status_code == 409 and locked.json()["detail"]["code"] == "STAGE_LOCKED"

    a1 = (await _start(client, hs, aid[S.APTITUDE], app_id)).json()["id"]
    j = (await journey(hs)).json()
    assert [s["status"] for s in j["stages"]] == ["IN_PROGRESS", "LOCKED", "LOCKED"] and j["status"].endswith("ASSESSMENT_PENDING")
    sess = (await client.get(f"/assessments/attempts/{a1}", headers=hs)).json()
    blob = str(sess)
    assert "correct_option_index" not in blob and "explanation" not in blob and "rubric" not in blob  # no answer keys for the candidate
    first = sess["sections"][0]["questions"][0]
    assert (await client.put(f"/assessments/attempts/{a1}/answers", headers=hs, json={"assessment_question_id": first["id"], "selected_option_index": 1})).status_code == 200
    assert (await client.post(f"/assessments/attempts/{a1}/submit", headers=hs)).json()["completed"]
    j = (await journey(hs)).json()
    assert [s["status"] for s in j["stages"]] == ["COMPLETED", "AVAILABLE", "LOCKED"]
    assert (await _start(client, hs, aid[S.CODING], app_id)).status_code == 409  # still cannot skip ahead

    a2 = (await _start(client, hs, aid[S.TECHNICAL], app_id)).json()["id"]
    assert a2 != a1
    assert (await client.post(f"/assessments/attempts/{a2}/submit", headers=hs)).json()["completed"]
    a3 = (await _start(client, hs, aid[S.CODING], app_id)).json()["id"]
    j = (await journey(hs)).json()
    assert [s["status"] for s in j["stages"]] == ["COMPLETED", "COMPLETED", "IN_PROGRESS"]
    assert (await client.post(f"/assessments/attempts/{a3}/submit", headers=hs)).json()["completed"]
    j = (await journey(hs)).json()
    assert all(s["status"] == "COMPLETED" for s in j["stages"]) and j["status"].endswith("UNDER_REVIEW")  # an assessments-only pipeline ends here

    async with AsyncSessionLocal() as db:
        attempts = {str(a.assessment_id): a for a in (await db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.application_id == app_.id))).all()}
        mins = {t: round((attempts[aid[t]].expires_at - attempts[aid[t]].started_at).total_seconds() / 60) for t in aid}
        assert mins == {S.APTITUDE: 20, S.TECHNICAL: 35, S.CODING: 50}  # separate timers, not one shared clock
        assert len({a.version_id for a in attempts.values()}) == 3 and None not in {a.version_id for a in attempts.values()}  # separate frozen versions
        assert attempts[aid[S.APTITUDE]].total_score == pytest.approx(1 / 3)
        # aptitude produced no skill evidence; technical MCQ/written answers left blank produced zero-score evidence only
        apt_answers = (await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == made[S.APTITUDE][1].id))).all()
        assert await db.scalar(select(func.count()).select_from(SkillEvidence).where(SkillEvidence.source_id.in_(apt_answers))) == 0
        rows = (await db.scalars(select(ApplicationStageProgress).where(ApplicationStageProgress.application_id == app_.id))).all()
        assert len(rows) == 3 and all(r.completed_at and r.result_reference["type"] == "assessment_attempt" for r in rows)
    # a finished stage cannot be re-entered, and a refresh returns the same attempt
    assert (await _start(client, hs, aid[S.APTITUDE], app_id)).json()["id"] == a1


@pytest.mark.asyncio
async def test_disabled_stages_are_neither_shown_nor_required(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "SkipCo", JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.TECHNICAL])
        tech = await make_stage_assessment(db, org, job, S.TECHNICAL)
        apt = await make_stage_assessment(db, org, job, S.APTITUDE)
        (await db.scalar(select(HiringStage).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.APTITUDE))).enabled = False
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        await db.commit()
    j = (await client.get(f"/hiring-pipeline/applications/{app_.id}", headers=hs)).json()
    assert [s["stage_type"] for s in j["stages"]] == [S.TECHNICAL] and j["stages"][0]["status"] == "AVAILABLE"
    blocked = await _start(client, hs, str(apt[1].id), str(app_.id))
    assert blocked.status_code == 409  # a disabled stage cannot be entered
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(ApplicationStageProgress).where(ApplicationStageProgress.application_id == app_.id)) == 1


@pytest.mark.asyncio
async def test_apply_creates_progress_and_a_stage_specific_notification(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "ApplyCo", JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.APTITUDE, S.HR_INTERVIEW])
        st, _, hs = await make_student(db)
        await db.commit()
    r = await client.post("/applications", headers=hs, json={"job_id": str(job.id)})
    assert r.status_code == 200
    j = (await client.get(f"/hiring-pipeline/applications/{r.json()['id']}", headers=hs)).json()
    assert [(s["stage_type"], s["status"]) for s in j["stages"]] == [(S.APTITUDE, "AVAILABLE"), (S.HR_INTERVIEW, "LOCKED")]
    async with AsyncSessionLocal() as db:
        from app.models.misc import Notification

        titles = (await db.scalars(select(Notification.title).where(Notification.link == f"/student/applications/{r.json()['id']}"))).all()
        assert "Aptitude Assessment available" in titles  # names the exact stage, not just "assessment"


@pytest.mark.asyncio
async def test_interview_only_pipeline_starts_from_applied_and_finishes_under_review(client, gw, monkeypatch):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "HROnlyCo", JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.HR_INTERVIEW])
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        await db.commit()
    await P.fill_pool(job.id, S.HR_INTERVIEW)

    async def obs(turn):
        return {"type": "hr_observation", "summary": "ok", "key_points": ["a"], "gave_concrete_example": True, "addressed_question": True}
    monkeypatch.setattr(iv_api, "evaluate_hr_answer", obs)
    iv = (await client.post("/interviews/start", headers=hs, json={"application_id": str(app_.id), "stage_type": S.HR_INTERVIEW})).json()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Application, app_.id)).status in (ApplicationStatus.INTERVIEW_PENDING, "INTERVIEW_PENDING")  # APPLIED -> INTERVIEW_PENDING is allowed
    n = 0
    while (t := (await client.post(f"/interviews/{iv['id']}/next-turn", headers=hs)).json()) is not None:
        await client.post(f"/interviews/turns/{t['id']}/answer", headers=hs, json={"answer_text": "I like clear plans and regular updates. " * 3})
        n += 1
        assert n < 20
    assert 5 <= n <= 8
    async with AsyncSessionLocal() as db:
        assert (await db.get(Application, app_.id)).status in (ApplicationStatus.UNDER_REVIEW, "UNDER_REVIEW")


# ------------------------------------------------------------------ technical + HR interviews
def _scripted_eval(monkeypatch, scores):
    seq = iter(scores)
    calls = {"n": 0}

    async def ev(turn):
        calls["n"] += 1
        s = next(seq, 0.6)
        return RubricEvaluation(concept_accuracy=s, reasoning=s, completeness=s, communication=s, demonstrated_concepts=["x"], missing_concepts=[],
                                evaluator_confidence=0.9)
    monkeypatch.setattr(iv_api, "evaluate_turn_answer", ev)
    return calls


@pytest.mark.asyncio
async def test_technical_then_hr_interview_end_to_end(client, gw, monkeypatch):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "IvCo", JobStatus.PUBLISHED)
        await configure_pipeline(db, job, [S.TECHNICAL, S.TECH_INTERVIEW, S.HR_INTERVIEW], {S.TECH_INTERVIEW: 60})
        tech = await make_stage_assessment(db, org, job, S.TECHNICAL, n=2)
        ti = await db.scalar(select(HiringStage).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.TECH_INTERVIEW))
        ti.question_count = None  # let the 60 minute duration set the length
        st, u_student, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        inst, _, ho = await make_institution(db, "PipeUni")
        st.institution_id = inst.id
        _, _, hother = await make_company(db, "SnoopCo")
        await db.commit()
    app_id, aid = str(app_.id), str(tech[1].id)
    fill = await P.fill_pool(job.id)
    assert fill["status"] == "READY" and fill["covered"] == 3
    hr_fill = await P.fill_pool(job.id, S.HR_INTERVIEW)
    assert hr_fill["status"] == "READY" and len(hr_fill["categories"]) >= 5

    # the technical assessment must be finished first; a locked interview cannot be started
    early = await client.post("/interviews/start", headers=hs, json={"application_id": app_id})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "STAGE_LOCKED"
    att = (await _start(client, hs, aid, app_id)).json()["id"]
    assert (await client.post(f"/assessments/attempts/{att}/submit", headers=hs)).json()["completed"]
    hr_early = await client.post("/interviews/start", headers=hs, json={"application_id": app_id, "stage_type": S.HR_INTERVIEW})
    assert hr_early.status_code == 409  # HR comes after the technical interview

    # ---- technical interview: many substantive turns, evidence-driven depth
    calls = _scripted_eval(monkeypatch, [0.9, 0.9, 0.85, 0.2, 0.3, 0.8, 0.9, 0.7, 0.9, 0.9, 0.5, 0.9])
    iv = (await client.post("/interviews/start", headers=hs, json={"application_id": app_id})).json()
    assert iv["stage_type"] == S.TECH_INTERVIEW and iv["max_turns"] == 10  # 60 minutes -> 10 questions
    asked, latencies = [], []
    while True:
        t0 = time.perf_counter()
        turn = (await client.post(f"/interviews/{iv['id']}/next-turn", headers=hs)).json()
        latencies.append(time.perf_counter() - t0)
        if turn is None:
            break
        assert set(turn) <= {"id", "turn_index", "skill_name", "question_text", "student_answer_text", "answer_source", "answered"}  # the question only: no layer, rubric or difficulty
        asked.append(turn["question_text"])
        r = await client.post(f"/interviews/turns/{turn['id']}/answer", headers=hs, json={"answer_text": "A reasonably detailed technical answer. " * 4})
        assert r.status_code == 200
        assert len(asked) <= 10
    assert 6 <= len(asked) <= 10 and len(set(asked)) == len(asked)  # several turns, never a repeat
    assert max(latencies[1:] or [0]) < 1.5  # every next question is a database lookup
    async with AsyncSessionLocal() as db:
        turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == iv["id"]).order_by(InterviewTurn.turn_index))).all()
        assert all(t.timing["path"] == "pool" and t.pool_question_id for t in turns)
        assert len({t.target_skill_id for t in turns}) >= 2  # more than one competency
        by_skill = {}
        for t in turns:
            by_skill.setdefault(t.target_skill_id, []).append(t)
        assert max(len(v) for v in by_skill.values()) >= 2  # at least one competency was drilled
        first = turns[0]
        assert first.layer == 1 and first.transcript_meta["mode"] == "start"
        second = turns[1]  # first answer scored 0.9 -> same competency, one layer deeper
        assert second.target_skill_id == first.target_skill_id and second.layer == 2 and second.transcript_meta["mode"] == "deeper"
        modes = [t.transcript_meta["mode"] for t in turns]
        assert "deeper" in modes and ("diagnostic" in modes or "switch" in modes)  # weak answers changed the course
        assert all(t.rubric_evaluation for t in turns)  # every turn scored against the same rubric
        assert (await db.get(Interview, iv["id"])).status == "COMPLETED"
        assert (await db.get(Application, app_.id)).status in (ApplicationStatus.INTERVIEW_PENDING, "INTERVIEW_PENDING")  # HR is still to come
        prog = {s.stage_type: p.status for s, p in [(await db.get(HiringStage, p.hiring_stage_id), p) for p in
                                                    (await db.scalars(select(ApplicationStageProgress).where(ApplicationStageProgress.application_id == app_.id))).all()]}
        assert prog == {S.TECHNICAL: "COMPLETED", S.TECH_INTERVIEW: "COMPLETED", S.HR_INTERVIEW: "AVAILABLE"}
        ev_before = await db.scalar(select(func.count()).select_from(SkillEvidence).where(SkillEvidence.student_id == st.id))

    # ---- HR interview: separate stage, separate questions, no scores, no evidence
    async def obs(turn):
        return {"type": "hr_observation", "version": "hr_observation_v1", "summary": "Gave an example.", "key_points": ["Cited a team project"],
                "gave_concrete_example": True, "addressed_question": True}
    monkeypatch.setattr(iv_api, "evaluate_hr_answer", obs)
    hr = (await client.post("/interviews/start", headers=hs, json={"application_id": app_id, "stage_type": S.HR_INTERVIEW})).json()
    assert hr["stage_type"] == S.HR_INTERVIEW and hr["id"] != iv["id"] and hr["max_turns"] == 6
    hr_q = []
    while (t := (await client.post(f"/interviews/{hr['id']}/next-turn", headers=hs)).json()) is not None:
        hr_q.append(t)
        assert (await client.post(f"/interviews/turns/{t['id']}/answer", headers=hs, json={"answer_text": "I usually agree a plan early and check in often. " * 2})).status_code == 200
    assert len(hr_q) == 6
    assert not set(q["question_text"] for q in hr_q) & set(asked)  # separate question set
    from app.services.interviews.hr_safety import is_safe_question

    assert all(is_safe_question(q["question_text"]) for q in hr_q)
    assert not any("medical" in q["question_text"].lower() for q in hr_q)  # the unsafe generated question never entered the pool
    assert len({q["skill_name"] for q in hr_q}) >= 4  # rotation over categories (labels, not skills)
    async with AsyncSessionLocal() as db:
        hturns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == hr["id"]))).all()
        assert all(t.target_skill_id is None and t.category and t.rubric_evaluation["type"] == "hr_observation" for t in hturns)
        assert not any(k in str(t.rubric_evaluation) for t in hturns for k in ("concept_accuracy", "overall_score", "score"))
        assert await db.scalar(select(func.count()).select_from(SkillEvidence).where(SkillEvidence.student_id == st.id)) == ev_before  # HR adds no skill evidence
        assert await db.scalar(select(func.count()).select_from(SkillEvidence).where(SkillEvidence.source_id.in_([t.id for t in hturns]))) == 0
        assert (await db.get(Application, app_.id)).status in (ApplicationStatus.UNDER_REVIEW, "UNDER_REVIEW")

    # ---- who sees what
    student_view = (await client.get(f"/hiring-pipeline/applications/{app_id}", headers=hs)).json()
    company_view = (await client.get(f"/hiring-pipeline/applications/{app_id}", headers=hc)).json()
    officer_view = (await client.get(f"/hiring-pipeline/applications/{app_id}", headers=ho)).json()
    assert all("result" not in s for s in student_view["stages"]) and all("result" not in s for s in officer_view["stages"])
    assert [s["status"] for s in officer_view["stages"]] == ["COMPLETED"] * 3 and all("assessment_id" not in s and "duration_minutes" not in s for s in officer_view["stages"])
    res = {s["stage_type"]: s["result"] for s in company_view["stages"]}
    assert res[S.TECHNICAL]["kind"] == "assessment" and res[S.TECH_INTERVIEW]["turns"] == len(asked) and res[S.TECH_INTERVIEW]["competencies"]
    assert res[S.HR_INTERVIEW]["observations"] and res[S.HR_INTERVIEW]["observations"][0]["key_points"] and "score" not in str(res[S.HR_INTERVIEW])
    assert "question_text" not in str(officer_view) and "correct_option" not in str(student_view)
    assert (await client.get(f"/hiring-pipeline/applications/{app_id}", headers=hother)).status_code in (403, 404)  # another company
    # the interview record for HR is not visible as the technical interview
    tech_only = (await client.get(f"/interviews/by-application/{app_id}", headers=hs)).json()
    assert tech_only["id"] == iv["id"]
    assert (await client.get(f"/interviews/by-application/{app_id}?stage_type=HR_INTERVIEW", headers=hs)).json()["id"] == hr["id"]


# ------------------------------------------------------------------ domains, sources and isolation
@pytest.mark.asyncio
async def test_aptitude_technical_and_coding_content_never_mix(client):
    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "MixCo")
        apt = await make_stage_assessment(db, org, job, S.APTITUDE, published=False)
        tech = await make_stage_assessment(db, org, job, S.TECHNICAL, published=False)
        code = await make_stage_assessment(db, org, job, S.CODING, published=False)
        await db.commit()
    apt_q, tech_q, code_q = apt[3][0], tech[3][0], code[3][0]
    ok = await client.post(f"/assessments/{apt[1].id}/questions", headers=hc, json={"question_id": str(apt_q.id) + "x"})
    assert ok.status_code in (404, 422)
    for aid, qid, expect in ((tech[1].id, apt_q.id, 409), (code[1].id, apt_q.id, 409), (apt[1].id, tech_q.id, 409), (tech[1].id, code_q.id, 409), (code[1].id, tech_q.id, 409)):
        r = await client.post(f"/assessments/{aid}/questions", headers=hc, json={"question_id": str(qid)})
        assert r.status_code == expect, (r.text, aid)
    fresh_apt = None
    async with AsyncSessionLocal() as db:
        q = Question(question_text="Another aptitude question: what is 7 times 8?", question_type=QuestionType.MCQ, skill_id=None, domain="APTITUDE",
                     category="Quantitative Aptitude", options=["54", "56", "58", "64"], correct_option_index=1, difficulty="easy",
                     source_type=QuestionSourceType.COMPANY_PRIVATE, organization_id=org.id, visibility=Visibility.COMPANY_PRIVATE, status=QuestionStatus.VALIDATED)
        db.add(q)
        await db.commit()
        fresh_apt = q.id
    r = await client.post(f"/assessments/{apt[1].id}/questions", headers=hc, json={"question_id": str(fresh_apt)})
    assert r.status_code == 200  # aptitude into aptitude is fine (skill-less question, sectioned by category)


@pytest.mark.asyncio
async def test_company_private_aptitude_and_interview_content_is_tenant_isolated(client, gw):
    token = f"A_ONLY_PRIVATE_TOKEN_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        org_a, rec_a, hc_a, job_a = await _company(db, "IsoA")
        org_b, rec_b, hc_b, job_b = await _company(db, "IsoB")
        for j in (job_a, job_b):
            await configure_pipeline(db, j, [S.APTITUDE, S.TECH_INTERVIEW], {})
            for row in (await db.scalars(select(HiringStage).where(HiringStage.job_id == j.id))).all():
                if row.stage_type == S.APTITUDE:
                    row.question_count, row.config = 3, {"categories": {"Quantitative Aptitude": 100}, "difficulty": {"easy": 0, "medium": 100, "hard": 0}}
        py = await skill(db, "Python")
        db.add(Question(question_text=f"{token} What is 6 times 7?", question_type=QuestionType.MCQ, skill_id=None, domain="APTITUDE", category="Quantitative Aptitude",
                        options=["36", "42", "44", "48"], correct_option_index=1, difficulty="medium", source_type=QuestionSourceType.COMPANY_PRIVATE,
                        organization_id=org_a.id, visibility=Visibility.COMPANY_PRIVATE, status=QuestionStatus.VALIDATED))
        db.add(Question(question_text=f"{token} Explain Python's GIL and when it matters for a CPU-bound service.", question_type=QuestionType.TECHNICAL, skill_id=py.id,
                        domain="TECHNICAL_INTERVIEW", difficulty="medium", source_type=QuestionSourceType.COMPANY_PRIVATE, organization_id=org_a.id,
                        visibility=Visibility.COMPANY_PRIVATE, status=QuestionStatus.VALIDATED, expected_concepts=["gil"], rubric={"criteria": ["gil"]}))
        await db.commit()
    from app.services.pipeline import stage_content as SC

    ra = await SC.generate_stage(job_a.id, S.APTITUDE, None)
    rb = await SC.generate_stage(job_b.id, S.APTITUDE, None)
    assert ra["reused_company"] == 1 and rb["reused_company"] == 0 and rb["generated"] == 3  # A reuses its own bank; B never sees it
    fa = await P.fill_pool(job_a.id)
    fb = await P.fill_pool(job_b.id)
    assert fa["from_bank"] >= 1  # A reuses its own interview-domain question (B may only ever get platform questions)
    async with AsyncSessionLocal() as db:
        b_stage = await db.scalar(select(HiringStage).where(HiringStage.job_id == job_b.id, HiringStage.stage_type == S.APTITUDE))
        b_texts = (await db.scalars(select(Question.question_text).join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
                                    .where(AssessmentQuestion.assessment_id == b_stage.assessment_id))).all()
        assert b_texts and not any(token in t for t in b_texts)
        b_pool = (await db.scalars(select(InterviewPoolQuestion.question_text).join(P.InterviewTemplate, P.InterviewTemplate.id == InterviewPoolQuestion.template_id)
                                   .where(P.InterviewTemplate.job_id == job_b.id))).all()
        assert b_pool and not any(token in t for t in b_pool)
        a_qid = await db.scalar(select(Question.id).where(Question.question_text.like(f"{token}%"), Question.domain == "APTITUDE"))
    assert not any(token in p for p in gw.prompts)  # nothing of A's content reached a model prompt (A's or B's generation)
    # B cannot attach, read or search A's private questions
    r = await client.post(f"/assessments/{b_stage.assessment_id}/questions", headers=hc_b, json={"question_id": str(a_qid)})
    assert r.status_code == 404
    listing = await client.get("/questions", headers=hc_b)
    assert token not in listing.text
    # nor can B read A's pipeline or template
    assert (await client.get(f"/hiring-pipeline/jobs/{job_a.id}", headers=hc_b)).status_code in (403, 404)
    assert (await client.get(f"/interviews/templates/by-job/{job_a.id}", headers=hc_b)).status_code in (403, 404)
    assert (await client.post(f"/hiring-pipeline/jobs/{job_a.id}/stages/{S.APTITUDE}/generate", headers=hc_b)).status_code in (403, 404)


@pytest.mark.asyncio
async def test_generated_aptitude_questions_are_independently_verified(gw, monkeypatch):
    """A question whose independent re-solve disagrees with its answer key is rejected, never stored."""
    from app.services.pipeline import stage_content as SC

    async with AsyncSessionLocal() as db:
        org, rec, hc, job = await _company(db, "VerifyCo")
        await configure_pipeline(db, job, [S.APTITUDE])
        row = await db.scalar(select(HiringStage).where(HiringStage.job_id == job.id, HiringStage.stage_type == S.APTITUDE))
        row.question_count, row.config = 2, {"categories": {"Logical Reasoning": 100}, "difficulty": {"easy": 100, "medium": 0, "hard": 0}}
        await db.commit()
    original = gw.generate_structured

    async def disagreeing(prompt, schema, **kw):
        if schema is SC._Solve:
            gw.prompts.append(prompt)
            return SC._Solve(answer_index=3)  # never matches the key (index 1)
        return await original(prompt, schema, **kw)
    monkeypatch.setattr(gw, "generate_structured", disagreeing)
    res = await SC.generate_stage(job.id, S.APTITUDE, None)
    assert res["covered_slots"] == 0 and res["missing_slots"] == 2 and res["generated"] == 0
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Question).where(Question.organization_id == org.id, Question.domain == "APTITUDE")) == 0
