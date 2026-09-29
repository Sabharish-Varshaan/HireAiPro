"""Interview template/pool: authoring-time preparation, deterministic selection, no model call on the candidate path."""
import time

import pytest
from sqlalchemy import select

from app.agents import interview_agent as IA
from app.core.database import AsyncSessionLocal
from app.models.enums import ApplicationStatus, QuestionStatus, QuestionType, Visibility
from app.models.interviews import InterviewPoolQuestion, InterviewTemplate, InterviewTurn
from app.models.questions import Question
from app.services.interviews import pool as P
from tests.factories import make_application, make_company, make_job, make_student, skill


class FakeGW:
    def __init__(self):
        self.calls = 0

    async def generate_structured(self, prompt, schema, **kw):
        self.calls += 1
        return schema(question_text=f"Prepared question number {self.calls}: explain the trade-offs involved here in detail.",
                      reason_for_question="tests a core competency")


@pytest.fixture
async def ctx(monkeypatch):
    gw = FakeGW()
    monkeypatch.setattr(P, "get_ai_gateway", lambda: gw)
    monkeypatch.setattr(P, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(P, "to_source_refs", lambda docs: [])
    async with AsyncSessionLocal() as db:
        org, rec, hc = await make_company(db, "PoolCo")
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0), ("PostgreSQL", "required", 0.6, 0.8), ("Git", "preferred", 0.4, 0.5)])
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st, ApplicationStatus.ASSESSMENT_COMPLETED)
        py = await skill(db, "Python")
        bank = Question(question_text="Explain how CPython's memory management works and where it can leak.", question_type=QuestionType.TECHNICAL,
                        skill_id=py.id, difficulty="medium", status=QuestionStatus.APPROVED, visibility=Visibility.PLATFORM_PUBLIC,
                        source_type="PLATFORM", expected_concepts=["refcount", "gc"], rubric={"criteria": ["a"]})
        db.add(bank)
        _, _, hb = await make_company(db, "OtherPoolCo")
        await db.commit()
        return dict(job=job.id, app=str(app_.id), hs=hs, hc=hc, hb=hb, gw=gw)


@pytest.mark.asyncio
async def test_pool_prefers_bank_generates_the_rest_and_is_idempotent(ctx):
    r = await P.fill_pool(ctx["job"])
    assert r["status"] == "READY" and r["from_bank"] == 1 and r["generated"] == 3 * 3 - 1  # 3 skills x 3 difficulties
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(InterviewPoolQuestion))).all()
        mine = [x for x in rows if x.template_id == (await db.scalar(select(InterviewTemplate.id).where(InterviewTemplate.job_id == ctx["job"])))]
        assert len({(x.skill_id, x.difficulty) for x in mine}) == 9
        assert len({x.content_hash for x in mine}) == len(mine)
        assert [x.source for x in mine].count("question_bank") == 1
    calls = ctx["gw"].calls
    again = await P.fill_pool(ctx["job"])
    assert again["added"] == 0 and ctx["gw"].calls == calls  # nothing regenerated


@pytest.mark.asyncio
async def test_candidate_path_uses_pool_without_any_model_call(client, ctx, monkeypatch):
    await P.fill_pool(ctx["job"])
    class Boom:
        def __getattr__(self, n):
            raise AssertionError("no model may be called to produce a pooled question")
    monkeypatch.setattr(IA, "get_ai_gateway", lambda: Boom())
    monkeypatch.setattr(IA, "run_llm_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("agent must not run")))
    iv = (await client.post("/interviews/start", headers=ctx["hs"], json={"application_id": ctx["app"]})).json()
    t = time.perf_counter()
    r = await client.post(f"/interviews/{iv['id']}/next-turn", headers=ctx["hs"])
    ms = (time.perf_counter() - t) * 1000
    assert r.status_code == 200 and r.json()["question_text"].startswith(("Prepared question", "Explain how CPython"))
    assert ms < 1500  # DB lookup, not a model call (baseline was p50 16.9 s)
    async with AsyncSessionLocal() as db:
        turn = await db.scalar(select(InterviewTurn).where(InterviewTurn.interview_id == iv["id"]))
        assert turn.timing["path"] == "pool" and turn.pool_question_id and turn.timing["total_ms"] < 1500
        from app.models.interviews import Interview
        plan = (await db.get(Interview, iv["id"])).plan
        assert plan["competencies"] and plan["pool"]["ready"]
    assert "timing" not in r.text and "pool" not in r.text.lower().replace("prepared", "")  # student view carries no internals


@pytest.mark.asyncio
async def test_selection_follows_difficulty_never_repeats_and_falls_back_to_live_path(client, ctx, monkeypatch):
    await P.fill_pool(ctx["job"])
    iv = (await client.post("/interviews/start", headers=ctx["hs"], json={"application_id": ctx["app"]})).json()
    seen = []
    for _ in range(3):
        turn = await client.post(f"/interviews/{iv['id']}/next-turn", headers=ctx["hs"])
        assert turn.status_code == 200
        seen.append(turn.json()["question_text"])
        async with AsyncSessionLocal() as db:  # mark answered so the next call advances (evaluation is a separate concern)
            t = await db.scalar(select(InterviewTurn).where(InterviewTurn.id == turn.json()["id"]))
            t.student_answer_text = "answered"
            await db.commit()
    assert len(set(seen)) == 3
    # empty the pool for this job -> the slower live path is used and labelled as such
    async with AsyncSessionLocal() as db:
        tid = await db.scalar(select(InterviewTemplate.id).where(InterviewTemplate.job_id == ctx["job"]))
        for t in (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == iv["id"]))).all():
            t.pool_question_id = None  # turns keep their text; only the pool is emptied
        await db.flush()
        for row in (await db.scalars(select(InterviewPoolQuestion).where(InterviewPoolQuestion.template_id == tid))).all():
            await db.delete(row)
        await db.commit()

    async def fake_agent(*a, **k):
        raise RuntimeError("force fallback")
    monkeypatch.setattr(IA, "run_llm_agent", fake_agent)

    class LiveGW:
        async def generate_structured(self, prompt, schema, **kw):
            return schema(question_text="Live generated question about the selected competency, please answer.", reason_for_question="live")
    monkeypatch.setattr(IA, "get_ai_gateway", lambda: LiveGW())
    monkeypatch.setattr(IA, "retrieve", lambda *a, **k: [])
    r = await client.post(f"/interviews/{iv['id']}/next-turn", headers=ctx["hs"])
    assert r.status_code == 200 and r.json()["question_text"].startswith("Live generated")
    async with AsyncSessionLocal() as db:
        last = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == iv["id"]).order_by(InterviewTurn.turn_index.desc()))).first()
        assert last.timing["path"] == "live_fallback" and last.timing["pool_miss_ms"] >= 0


@pytest.mark.asyncio
async def test_readiness_prepare_and_recruiter_template_isolation(client, ctx, monkeypatch):
    from app.api.v1 import interviews as api
    kicked = []
    monkeypatch.setattr(api, "_kick_prepare", lambda job_id: kicked.append(job_id))
    r = await client.get(f"/interviews/readiness/{ctx['app']}", headers=ctx["hs"])
    assert r.json() == {"ready": False, "status": "MISSING"}
    prep = await client.post("/interviews/prepare", headers=ctx["hs"], json={"application_id": ctx["app"]})
    assert prep.status_code == 200 and prep.json()["status"] == "PREPARING" and kicked == [ctx["job"]]
    await P.fill_pool(ctx["job"])
    assert (await client.get(f"/interviews/readiness/{ctx['app']}", headers=ctx["hs"])).json()["ready"] is True
    view = await client.get(f"/interviews/templates/by-job/{ctx['job']}", headers=ctx["hc"])
    assert view.status_code == 200 and view.json()["status"] == "READY" and len(view.json()["questions"]) == 9
    assert view.json()["config"]["rubric"]["version"] == "interview_rubric_v1"
    assert (await client.get(f"/interviews/templates/by-job/{ctx['job']}", headers=ctx["hb"])).status_code in (403, 404)  # other company
    assert (await client.get(f"/interviews/templates/by-job/{ctx['job']}", headers=ctx["hs"])).status_code == 403  # student
    assert (await client.post(f"/interviews/templates/by-job/{ctx['job']}/rebuild", headers=ctx["hb"])).status_code in (403, 404)


@pytest.mark.asyncio
async def test_slow_scoring_never_blocks_the_next_question_and_is_recorded_once(client, ctx, monkeypatch):
    import asyncio

    from app.api.v1 import interviews as api
    from app.models.evidence import SkillEvidence
    from app.schemas.rubric import RubricEvaluation

    await P.fill_pool(ctx["job"])
    calls = {"n": 0}

    async def slow_eval(turn):
        calls["n"] += 1
        await asyncio.sleep(1.5)  # a slow provider
        return RubricEvaluation(concept_accuracy=0.8, reasoning=0.7, completeness=0.7, communication=0.8,
                                demonstrated_concepts=["a"], missing_concepts=[], evaluator_confidence=0.9)
    monkeypatch.setattr(api, "evaluate_turn_answer", slow_eval)
    monkeypatch.setattr(api.settings, "INTERVIEW_EVAL_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(api.settings, "INTERVIEW_EVAL_CATCHUP_SECONDS", 0.2)
    iv = (await client.post("/interviews/start", headers=ctx["hs"], json={"application_id": ctx["app"]})).json()
    q1 = (await client.post(f"/interviews/{iv['id']}/next-turn", headers=ctx["hs"])).json()
    t = time.perf_counter()
    ans = await client.post(f"/interviews/turns/{q1['id']}/answer", headers=ctx["hs"], json={"answer_text": "My answer " * 10, "answer_source": "text"})
    answer_s = time.perf_counter() - t
    assert ans.status_code == 200 and ans.json()["answered"] and answer_s < 1.0  # budget, not the 1.5 s the provider needs
    assert ans.json()["student_answer_text"].startswith("My answer")  # persisted immediately
    async with AsyncSessionLocal() as db:
        assert (await db.scalar(select(InterviewTurn).where(InterviewTurn.id == q1["id"]))).rubric_evaluation is None  # still scoring
    t = time.perf_counter()
    q2 = await client.post(f"/interviews/{iv['id']}/next-turn", headers=ctx["hs"])
    assert q2.status_code == 200 and q2.json()["id"] != q1["id"] and time.perf_counter() - t < 1.2
    await asyncio.sleep(1.6)  # the background scoring completes
    async with AsyncSessionLocal() as db:
        scored = await db.scalar(select(InterviewTurn).where(InterviewTurn.id == q1["id"]))
        assert scored.rubric_evaluation is not None and scored.timing["answer"]["eval_ms"] >= 1400
        n = len((await db.scalars(select(SkillEvidence).where(SkillEvidence.source_id == scored.id))).all())
    assert n == 1 and calls["n"] == 1  # scored exactly once; the re-answer below is a no-op
    again = await client.post(f"/interviews/turns/{q1['id']}/answer", headers=ctx["hs"], json={"answer_text": "ignored", "answer_source": "text"})
    assert again.status_code == 200 and calls["n"] == 1
    # finishing waits for any unscored answers so the recruiter's evidence is complete
    a2 = await client.post(f"/interviews/turns/{q2.json()['id']}/answer", headers=ctx["hs"], json={"answer_text": "Second answer " * 5, "answer_source": "text"})
    assert a2.status_code == 200
    fin = await client.post(f"/interviews/{iv['id']}/finish", headers=ctx["hs"])
    assert fin.status_code == 200
    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == iv["id"]))).all()
        assert all(r.rubric_evaluation is not None for r in rows if r.student_answer_text)
