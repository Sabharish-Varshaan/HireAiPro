import uuid

import pytest
from sqlalchemy import select

from app.agents import assessment_agent as AA, career_agent as CA, interview_agent as IA, knowledge_agent as KA
from app.core.database import AsyncSessionLocal
from app.models.career import LearningPathStep, LearningResource
from app.models.enums import EvidenceSourceType as E, JobStatus, QuestionSourceType, QuestionStatus, QuestionType, Visibility
from app.models.interviews import Interview, InterviewTurn
from app.models.misc import AgentRun
from app.models.questions import Question
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.evidence.service import record_evidence
from tests.agents.scripted import call, final, scripted
from tests.factories import make_application, make_company, make_job, make_student, skill, uniq
from tests.fakes import FakeLLM


async def last_run(agent_type: str) -> AgentRun:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AgentRun).where(AgentRun.agent_type == agent_type).order_by(AgentRun.created_at.desc()))


# ---------------- Knowledge Agent ----------------

@pytest.mark.asyncio
async def test_knowledge_agent_executes_every_tool_and_reconciles_output():
    uri = f"inline:{uniq('ka')}"
    text = "Redis sorted sets keep members ordered by score.\n\n" * 30
    src_holder = {}

    def remember(last):
        src_holder["id"] = last["source_id"]
        return ("fetch_source", {"source_id": last["source_id"]})

    model = scripted([
        call("get_skill"), call("get_existing_sources"), call("register_source", index=0), remember,
        lambda l: ("extract_text", {"source_id": src_holder["id"]}),
        lambda l: ("chunk_text", {"source_id": src_holder["id"]}),
        lambda l: ("embed_chunks", {"source_id": src_holder["id"]}),
        lambda l: ("store_chunks", {"source_id": src_holder["id"]}),
        lambda l: ("mark_ready", {"source_id": src_holder["id"]}),
        # the "model" reports nonsense counts; the agent must return the real ones
        final(skill_id=str(uuid.uuid4()), source_ids=[], sources_processed=99, chunks_created=12345, status="READY", errors=[]),
    ])
    async with AsyncSessionLocal() as db:
        with KA.knowledge_agent.override(model=model):
            pkg = await KA.run_knowledge_agent(db, skill_name="Redis", sources=[
                KA.SourceSpec(title="redis notes", source_type="INLINE_TEXT", source_uri=uri, raw_text=text)])
    assert pkg.status == "READY" and pkg.sources_processed == 1 and 0 < pkg.chunks_created < 100
    run = await last_run("knowledge_agent")
    assert run.status == "COMPLETED" and not run.used_fallback
    assert [c["tool"] for c in run.tool_calls] == ["get_skill", "get_existing_sources", "register_source", "fetch_source",
                                                  "extract_text", "chunk_text", "embed_chunks", "store_chunks", "mark_ready"]


@pytest.mark.asyncio
async def test_knowledge_agent_falls_back_when_model_skips_tools():
    model = scripted([final(skill_id=str(uuid.uuid4()), source_ids=[], sources_processed=1, chunks_created=5, status="READY", errors=[])])
    async with AsyncSessionLocal() as db:
        with KA.knowledge_agent.override(model=model):
            pkg = await KA.run_knowledge_agent(db, skill_name="Redis", sources=[
                KA.SourceSpec(title="fb", source_type="INLINE_TEXT", source_uri=f"inline:{uniq('fb')}",
                              raw_text="Redis streams are append-only logs.\n\n" * 20)])
    run = await last_run("knowledge_agent")
    assert run.used_fallback and run.status == "COMPLETED" and run.error.startswith("LLM orchestration failed")
    assert pkg.status == "READY" and pkg.chunks_created > 0


# ---------------- Interview Agent ----------------

async def _interview(db):
    org, rec, _ = await make_company(db)
    job = await make_job(db, org, rec, [("Python", "required", 0.7, 1.0), ("Docker", "required", 0.5, 0.8), ("AWS", "required", 0.5, 0.4)])
    st, _, _ = await make_student(db)
    py = await skill(db, "Python")
    for t in (E.CODING, E.MCQ, E.INTERVIEW, E.TECHNICAL_ASSESSMENT):
        await record_evidence(db, st.id, py.id, t, 0.95, confidence=0.95, idempotency_key=f"{t}{st.id}")
    await db.commit()
    await recalculate_all_skills_for_student(db, st.id)
    app_ = await make_application(db, job, st)
    iv = Interview(application_id=app_.id, student_id=st.id, job_id=job.id, max_turns=5)
    db.add(iv)
    await db.commit()
    return iv


@pytest.mark.asyncio
async def test_interview_agent_enforces_selection_boundary(monkeypatch):
    async with AsyncSessionLocal() as db:
        iv = await _interview(db)
        py, docker, aws = (await skill(db, "Python")).id, (await skill(db, "Docker")).id, (await skill(db, "AWS")).id
        model = scripted([
            call("rank_competencies"),
            call("get_interview_history"),
            # tries to drill the already-proven skill: must be refused
            call("save_interview_turn", skill_id=str(py), question_text="Explain Python generators in depth please.", reason="x"),
            call("retrieve_skill_knowledge", skill_id=str(docker)),
            call("save_interview_turn", skill_id=str(docker), question_text="How does Docker layer caching affect build times?", reason="no Docker evidence yet"),
            final(target_skill_id=str(docker), question_text="q", difficulty="hard", reason_for_question="r", should_continue=True),
        ])
        with IA.interview_agent.override(model=model):
            turn = await IA.decide_next_turn(db, iv)
        await db.commit()
    assert turn.target_skill_id == docker
    assert turn.difficulty == "easy"  # deterministic (no evidence), not the model's "hard"
    run = await last_run("interview_agent")
    rejected = [c for c in run.tool_calls if c["tool"] == "save_interview_turn" and "rejected" in c]
    assert rejected and rejected[0]["rejected"] == str(py) and not run.used_fallback


# ---------------- Assessment Agent ----------------

@pytest.mark.asyncio
async def test_assessment_agent_reuses_company_questions_then_generates(monkeypatch):
    FakeLLM(monkeypatch, {
        "GeneratedTechnicalQuestion": lambda p: {"question_text": f"Explain how Kubernetes rolling updates avoid downtime ({uuid.uuid4().hex[:6]}).",
                                                 "expected_concepts": ["readiness probe", "maxSurge"], "rubric_criteria": ["probes", "surge"]},
        "GeneratedMCQ": lambda p: {"question_text": f"Which Kubernetes object manages ReplicaSets ({uuid.uuid4().hex[:6]})?",
                                   "options": ["Deployment", "Service", "ConfigMap"], "correct_option_index": 0, "explanation": "x"},
    })
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Git", "required", 0.5, 1.0), ("Kubernetes", "required", 0.5, 1.0)],
                             status=JobStatus.REQUIREMENTS_CONFIRMED)
        git = await skill(db, "Git")
        for i in range(4):  # company bank already covers Git
            for qt in (QuestionType.TECHNICAL, QuestionType.MCQ):
                db.add(Question(question_text=f"Company Git question {i} {qt.value} {uuid.uuid4().hex[:6]}", question_type=qt,
                                skill_id=git.id, difficulty="medium", source_type=QuestionSourceType.COMPANY_PRIVATE,
                                organization_id=org.id, visibility=Visibility.COMPANY_PRIVATE, status=QuestionStatus.APPROVED,
                                options=["a", "b", "c"], correct_option_index=0, expected_concepts=["x", "y"], rubric={"criteria": ["c"]}))
        await db.commit()
        steps = [call("get_job_competencies"), call("build_assessment_blueprint")]
        for i in (0, 1):
            steps += [call("search_company_questions", skill_index=i), call("search_platform_questions", skill_index=i),
                      call("retrieve_knowledge", skill_index=i), call("generate_missing_question", skill_index=i)]
        steps += [call("create_assessment"), lambda last: ("__final__", last)]
        with AA.assessment_agent.override(model=scripted(steps)):
            plan = await AA.run_assessment_agent(db, await db.get(type(job), job.id), "Assessment", None)
    by = {s.skill_name: s for s in plan.sections}
    assert by["Git"].reused_company > 0 and by["Git"].generated == 0
    assert by["Kubernetes"].generated > 0
    run = await last_run("assessment_agent")
    assert run.status == "COMPLETED" and not run.used_fallback
    assert {"search_company_questions", "search_platform_questions", "retrieve_knowledge", "generate_missing_question",
            "create_assessment"} <= {c["tool"] for c in run.tool_calls}
    async with AsyncSessionLocal() as db:
        gen = (await db.scalars(select(Question).where(Question.generation_key.like(f"{job.id}:%")))).all()
    assert gen and all(q.organization_id == org.id and q.visibility == Visibility.COMPANY_PRIVATE for q in gen)
    assert all(q.status in (QuestionStatus.VALIDATED, "VALIDATED", QuestionStatus.DRAFT, "DRAFT") for q in gen)


# ---------------- Career Agent ----------------

@pytest.mark.asyncio
async def test_career_agent_drops_fabricated_resources_and_orders_prerequisites():
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Kubernetes", "required", 0.6, 1.0), ("FastAPI", "required", 0.6, 0.8)])
        st, _, _ = await make_student(db)
        await db.commit()
        k8s, docker, fastapi, rust = [(await skill(db, n)).id for n in ("Kubernetes", "Docker", "FastAPI", "Rust")]
        real = await db.scalar(select(LearningResource).where(LearningResource.skill_id == k8s))
        fake_id = uuid.uuid4()
        model = scripted([
            call("calculate_skill_gaps"),
            call("get_skill_prerequisites", skill_id=str(k8s)),
            call("search_learning_resources", skill_id=str(k8s)),
            call("save_learning_path", summary="Build container skills first.", steps=[
                {"skill_id": str(k8s), "rationale": "orchestrate", "resource_ids": [str(real.id), str(fake_id)]},
                {"skill_id": str(rust), "rationale": "not a gap", "resource_ids": []},
                {"skill_id": str(fastapi), "rationale": "api", "resource_ids": []}]),
            lambda last: ("__final__", last),
        ])
        with CA.career_agent.override(model=model):
            rm = await CA.build_career_roadmap(db, st.id, job.id)
    ids = [s.skill_id for s in rm.steps]
    assert rust not in ids  # model can't add non-gap skills
    assert docker in ids and ids.index(docker) < ids.index(k8s)  # prerequisite inserted before its dependent
    k8s_step = next(s for s in rm.steps if s.skill_id == k8s)
    assert [r.resource_id for r in k8s_step.resources] == [real.id]  # fabricated id dropped
    assert all(s.resources for s in rm.steps if s.skill_id in (k8s, fastapi))  # real resources exist for gaps
    async with AsyncSessionLocal() as db:
        stored = (await db.scalars(select(LearningPathStep).where(LearningPathStep.learning_path_id == rm.learning_path_id))).all()
        assert all(str(fake_id) not in (s.resource_ids or []) for s in stored)
    run = await last_run("career_agent")
    assert run.status == "COMPLETED" and not run.used_fallback


# ---------------- live: the real local model orchestrates ----------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_interview_agent_picks_uncertain_skill():
    async with AsyncSessionLocal() as db:
        iv = await _interview(db)
        turn = await IA.decide_next_turn(db, iv)
        await db.commit()
        names = {(await skill(db, n)).id: n for n in ("Python", "Docker", "AWS")}
    assert names[turn.target_skill_id] in {"Docker", "AWS"}
    run = await last_run("interview_agent")
    assert run.status == "COMPLETED"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_career_agent_returns_real_resources():
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Docker", "required", 0.6, 1.0), ("PostgreSQL", "required", 0.6, 0.8)])
        st, _, _ = await make_student(db)
        await db.commit()
        rm = await CA.build_career_roadmap(db, st.id, job.id)
        stored_ids = {r.id for r in (await db.scalars(select(LearningResource))).all()}
    assert rm.steps and all(r.resource_id in stored_ids for s in rm.steps for r in s.resources)
    assert any(s.resources for s in rm.steps)
