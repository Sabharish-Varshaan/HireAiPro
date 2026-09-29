"""Interview Agent (PydanticAI).

Decides the next interview turn. It reads the job requirements, the
student's current evidence and the interview so far, then must pick one of
the top-ranked competencies from the deterministic ranking (see
app.services.interviews.selector) and phrase a question for it, optionally
grounded on the question bank or approved knowledge. `save_interview_turn`
enforces the selection boundary and sets difficulty deterministically — the
model cannot hop to an arbitrary skill or choose its own difficulty.

It never scores answers into skill levels: answer scoring is the rubric
service → evidence service → SkillEstimator path in the API layer.
"""

import time
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ToolLog, build_agent, run_agent, run_llm_agent, tool_uuid
from app.models.assessments import AssessmentAnswer, AssessmentAttempt, AssessmentQuestion
from app.models.enums import QuestionStatus as QS, QuestionType, Visibility
from app.models.evidence import SkillEvidence
from app.models.interviews import Interview, InterviewTurn
from app.models.jobs import Job
from app.models.questions import Question
from app.schemas.interview import InterviewDecision
from app.schemas.rubric import RubricEvaluation
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.interviews import depth
from app.services.interviews.selector import SELECTION_WINDOW, Candidate, rank_candidates
from app.services.pipeline import stages as S
from app.services.knowledge.service import retrieve, to_source_refs


@dataclass
class InterviewDeps:
    db: AsyncSession
    interview: Interview
    job: Job
    log: ToolLog
    ranked: list[Candidate] = field(default_factory=list)
    saved_turn: InterviewTurn | None = None
    grounding: dict[str, list[dict]] = field(default_factory=dict)


INSTRUCTIONS = """You are an adaptive technical interviewer.
You have a small request budget: put independent tool calls in the SAME response.
1. Call rank_competencies to see which skills most need evidence.
2. Optionally call get_job_requirements, get_student_evidence and get_interview_history for context.
3. Pick ONE skill from the top of the ranking. Call search_question_bank and/or
   retrieve_skill_knowledge for it to ground your question.
4. Call save_interview_turn with that skill_id, one clear open-ended question (not yes/no,
   not a repeat of an earlier question) and a one-sentence reason.
5. Then reply with a one-line confirmation. If rank_competencies is empty, say so and stop."""

interview_agent = build_agent(InterviewDecision, InterviewDeps, INSTRUCTIONS, "interview_agent")


@interview_agent.tool
async def rank_competencies(ctx: RunContext[InterviewDeps]) -> list[dict]:
    """Deterministic priority ranking of competencies that still need evidence."""
    d = ctx.deps
    d.ranked = await rank_candidates(d.db, d.job.id, d.interview.student_id, d.interview.id)
    d.log.record("rank_competencies", top=[c.skill_name for c in d.ranked[:3]])
    return [c.as_dict() for c in d.ranked[:5]]


@interview_agent.tool
async def get_job_requirements(ctx: RunContext[InterviewDeps]) -> dict:
    """Job title and the skills it requires."""
    d = ctx.deps
    d.log.record("get_job_requirements")
    return {"job": d.job.title, "skills": [c.skill_name for c in d.ranked] or "call rank_competencies"}


@interview_agent.tool
async def get_student_evidence(ctx: RunContext[InterviewDeps], skill_id: str) -> list[dict]:
    """Existing verified evidence for the student on one skill (resume claims excluded)."""
    d = ctx.deps
    rows = (
        await d.db.scalars(
            select(SkillEvidence).where(
                SkillEvidence.student_id == d.interview.student_id,
                SkillEvidence.skill_id == tool_uuid(skill_id, "skill_id"),
                SkillEvidence.source_type != "RESUME_CLAIM",
                SkillEvidence.is_deleted.is_(False),
            )
        )
    ).all()
    d.log.record("get_student_evidence", skill_id=skill_id, count=len(rows))
    return [{"source": e.source_type, "score": round(e.normalized_score, 2), "difficulty": e.difficulty} for e in rows]


@interview_agent.tool
async def get_interview_history(ctx: RunContext[InterviewDeps]) -> list[dict]:
    """Questions already asked in this interview and how they were scored."""
    d = ctx.deps
    turns = (
        await d.db.scalars(
            select(InterviewTurn).where(InterviewTurn.interview_id == d.interview.id).order_by(InterviewTurn.turn_index)
        )
    ).all()
    d.log.record("get_interview_history", turns=len(turns))
    return [
        {"skill_id": str(t.target_skill_id), "question": t.question_text, "difficulty": t.difficulty,
         "answered": t.student_answer_text is not None,
         "score": (t.rubric_evaluation or {}).get("concept_accuracy")}
        for t in turns
    ]


async def _already_asked(d: InterviewDeps) -> tuple[set[uuid.UUID], set[str]]:
    """Question ids and normalised texts the candidate already saw in this
    application (its assessment attempt and earlier interview turns)."""
    ids = set(
        (
            await d.db.scalars(
                select(AssessmentQuestion.question_id)
                .join(AssessmentAnswer, AssessmentAnswer.assessment_question_id == AssessmentQuestion.id)
                .join(AssessmentAttempt, AssessmentAttempt.id == AssessmentAnswer.attempt_id)
                .where(AssessmentAttempt.application_id == d.interview.application_id)
            )
        ).all()
    )
    texts = {_norm(t) for t in (await d.db.scalars(select(Question.question_text).where(Question.id.in_(ids)))).all()} if ids else set()
    texts |= {
        _norm(t) for t in (
            await d.db.scalars(select(InterviewTurn.question_text).where(InterviewTurn.interview_id == d.interview.id))
        ).all()
    }
    return ids, texts


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@interview_agent.tool
async def search_question_bank(ctx: RunContext[InterviewDeps], skill_id: str) -> list[str]:
    """Up to 3 approved technical questions for the skill visible to this job's company,
    excluding any the candidate already answered in this application. Use them as
    inspiration; do not repeat them verbatim."""
    d = ctx.deps
    seen_ids, _ = await _already_asked(d)
    rows = (
        await d.db.scalars(
            select(Question).where(
                Question.id.not_in(seen_ids) if seen_ids else true(),
                Question.skill_id == tool_uuid(skill_id, "skill_id"),
                Question.question_type == QuestionType.TECHNICAL,
                Question.status.in_([QS.VALIDATED.value, QS.APPROVED.value, QS.ACTIVE.value]),
                (Question.visibility == Visibility.PLATFORM_PUBLIC) | (Question.organization_id == d.job.organization_id),
            ).limit(3)
        )
    ).all()
    d.log.record("search_question_bank", skill_id=skill_id, found=len(rows))
    return [q.question_text for q in rows]


@interview_agent.tool
async def retrieve_skill_knowledge(ctx: RunContext[InterviewDeps], skill_id: str) -> list[str]:
    """Top reranked approved-knowledge snippets for the skill, tenant-scoped to the job's company."""
    d = ctx.deps
    name = next((c.skill_name for c in d.ranked if str(c.skill_id) == skill_id), "")
    docs = retrieve(f"{name} core concepts", TenantScope(organization_id=d.job.organization_id),
                    skill_ids=[tool_uuid(skill_id, "skill_id")], top_k=20, top_n=2)
    d.grounding[skill_id] = to_source_refs(docs)
    d.log.record("retrieve_skill_knowledge", skill_id=skill_id, chunks=len(docs))
    return [x.text[:600] for x in docs]


@interview_agent.tool
async def save_interview_turn(ctx: RunContext[InterviewDeps], skill_id: str, question_text: str, reason: str) -> dict:
    """Persist the next question. skill_id must be one of the top-ranked competencies."""
    d = ctx.deps
    if not d.ranked:
        d.ranked = await rank_candidates(d.db, d.job.id, d.interview.student_id, d.interview.id)
    window = d.ranked[:SELECTION_WINDOW]
    chosen = next((c for c in window if str(c.skill_id) == skill_id), None)
    if chosen is None:
        d.log.record("save_interview_turn", rejected=skill_id)
        return {"error": f"skill must be one of {[c.skill_name + ':' + str(c.skill_id) for c in window]}"}
    if len(question_text.strip()) < 15:
        return {"error": "question is too short"}
    _, seen_texts = await _already_asked(d)
    if _norm(question_text) in seen_texts:
        d.log.record("save_interview_turn", rejected_repeat=skill_id)
        return {"error": "the candidate already answered this exact question; ask a different one"}
    turn = await _persist_turn(d, chosen, question_text.strip(), reason.strip())
    d.log.record("save_interview_turn", skill=chosen.skill_name, turn_id=turn.id)
    return {"turn_id": str(turn.id), "skill": chosen.skill_name, "difficulty": turn.difficulty}


async def _persist_turn(d: InterviewDeps, c: Candidate, question: str, reason: str) -> InterviewTurn:
    if d.saved_turn is not None:
        return d.saved_turn
    count = len((await d.db.scalars(select(InterviewTurn.id).where(InterviewTurn.interview_id == d.interview.id))).all())
    refs = d.grounding.get(str(c.skill_id)) or []
    turn = InterviewTurn(
        interview_id=d.interview.id, turn_index=count, target_skill_id=c.skill_id, question_text=question,
        difficulty=c.difficulty, reason_for_question=f"{reason} [{c.reason}]",
        transcript_meta={"source_refs": refs} if refs else None,
    )
    d.db.add(turn)
    await d.db.flush()
    d.saved_turn = turn
    return turn


class _Q(BaseModel):
    question_text: str
    reason_for_question: str


async def decide_next_turn(db: AsyncSession, interview: Interview, use_llm: bool = True) -> InterviewTurn | None:
    """Next turn for either interview stage. HR: category rotation over the HR pool. Technical: the frozen blueprint plus depth.plan_next choose
    the competency and depth layer, the prepared pool supplies the wording (a database lookup). Only when no prepared question can serve does the
    slower live path run (agent, then a single call)."""
    if interview.stage_type == S.HR_INTERVIEW:
        return await _decide_hr(db, interview)
    from app.services.interviews.pool import pool_rows, _template

    t0 = time.perf_counter()
    tpl = await _template(db, interview.job_id, S.TECH_INTERVIEW)
    rows = await pool_rows(db, tpl.id) if tpl is not None else []
    if tpl is not None and rows and (tpl.config or {}).get("blueprint"):
        outcome = await _decide_depth(db, interview, tpl, rows, t0)
        if outcome is not _MISS:
            return outcome
    return await _decide_live(db, interview, use_llm, t0)


_MISS = object()


async def _turn_states(db: AsyncSession, interview: Interview) -> tuple[list[InterviewTurn], list[depth.TurnState]]:
    turns = list((await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id).order_by(InterviewTurn.turn_index))).all())
    states = []
    for t in turns:
        sc, cf = depth.turn_score(t.rubric_evaluation)
        states.append(depth.TurnState(skill_id=str(t.target_skill_id), layer=t.layer or 2, score=sc, confidence=cf,
                                      mode=(t.transcript_meta or {}).get("mode", "start")))
    return turns, states


async def _decide_depth(db: AsyncSession, interview: Interview, tpl, rows, t0: float):
    from app.services.interviews.pool import _asked_texts

    cfg = tpl.config
    budget = min(interview.max_turns, cfg["question_budget"])
    comps = depth.comps_from_blueprint(cfg["blueprint"], budget)
    turns, states = await _turn_states(db, interview)
    seen = await _asked_texts(db, interview)
    exhausted: set[str] = set()
    t1 = time.perf_counter()
    while True:
        pick = depth.plan_next(comps, states, budget, exhausted, int(cfg.get("max_asks_per_competency", depth.DEFAULT_MAX_ASKS)))
        if pick is None:
            # finished normally, unless the pool ran dry before the minimum was reached -> let the live path top up
            return _MISS if (len(turns) < cfg.get("min_questions", 0) and len(turns) < budget) else None
        kinds = [t.kind for t in turns if str(t.target_skill_id) == pick.skill_id and t.kind]
        row = depth.choose_from_pool(rows, pick.skill_id, pick.layer, seen, kinds)
        if row is None:
            exhausted.add(pick.skill_id)
            continue
        turn = InterviewTurn(
            interview_id=interview.id, turn_index=len(turns), target_skill_id=row.skill_id, question_text=row.question_text,
            difficulty=row.difficulty, kind=row.kind, layer=row.layer, reason_for_question=pick.reason,
            transcript_meta={"mode": pick.mode, **({"source_refs": row.source_refs} if row.source_refs else {})}, pool_question_id=row.id,
            timing={"path": "pool", "pool_source": row.source, "mode": pick.mode, "plan_ms": round((time.perf_counter() - t1) * 1000, 1),
                    "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
        db.add(turn)
        await db.flush()
        return turn


async def _decide_hr(db: AsyncSession, interview: Interview) -> InterviewTurn | None:
    from app.services.interviews.hr import pick_hr_question
    from app.services.interviews.pool import _asked_texts, _template, pool_rows

    t0 = time.perf_counter()
    tpl = await _template(db, interview.job_id, S.HR_INTERVIEW)
    if tpl is None:
        return None
    cfg = tpl.config
    turns = list((await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id).order_by(InterviewTurn.turn_index))).all())
    if len(turns) >= min(interview.max_turns, cfg["question_budget"]):
        return None
    rows = await pool_rows(db, tpl.id)
    row = pick_hr_question(rows, list(cfg["categories"]), [t.category for t in turns if t.category], await _asked_texts(db, interview))
    if row is None:
        return None
    turn = InterviewTurn(interview_id=interview.id, turn_index=len(turns), target_skill_id=None, category=row.category, kind="behavioural",
                         question_text=row.question_text, difficulty="medium", reason_for_question=f"HR topic: {row.category}",
                         pool_question_id=row.id, timing={"path": "pool", "pool_source": row.source, "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
    db.add(turn)
    await db.flush()
    return turn


async def _decide_live(db: AsyncSession, interview: Interview, use_llm: bool, t0: float) -> InterviewTurn | None:
    """Controlled fallback: the ranked competency, asked live (agent, then a single call). Slower; labelled `live_fallback`."""
    job = await db.get(Job, interview.job_id)
    log = ToolLog()
    deps = InterviewDeps(db=db, interview=interview, job=job, log=log)
    count = len((await db.scalars(select(InterviewTurn.id).where(InterviewTurn.interview_id == interview.id))).all())
    ranked = await rank_candidates(db, job.id, interview.student_id, interview.id)
    rank_ms = (time.perf_counter() - t0) * 1000
    if not ranked or count >= interview.max_turns:
        return None
    t1 = time.perf_counter()

    async def llm() -> InterviewTurn:
        await run_llm_agent(interview_agent, "interview_agent", f"Choose the next question for the '{job.title}' interview.", deps, log)
        if deps.saved_turn is None:
            raise RuntimeError("agent did not save a turn")
        return deps.saved_turn

    async def fallback() -> InterviewTurn:
        deps.ranked = ranked
        top = ranked[0]
        docs = retrieve(f"{top.skill_name} core concepts", TenantScope(organization_id=job.organization_id),
                        skill_ids=[top.skill_id], top_k=20, top_n=2)
        deps.grounding[str(top.skill_id)] = to_source_refs(docs)
        ctx_txt = "\n\n".join(x.text[:600] for x in docs)
        q = await get_ai_gateway().generate_structured(
            (f"CONTEXT:\n{ctx_txt}\n\n" if ctx_txt else "")
            + f"Ask ONE {top.difficulty} open-ended interview question about '{top.skill_name}'.",
            _Q, task_type="interview_question", related_entity_type="interview", related_entity_id=interview.id,
        )
        log.record("fallback:save_interview_turn", skill=top.skill_name)
        return await _persist_turn(deps, top, q.question_text, q.reason_for_question)

    turn = await run_agent(
        agent_type="interview_agent", task=f"next_turn:{interview.id}", context_type="interview",
        context_id=interview.id, tool_log=log, run_llm=llm if use_llm else _disabled, fallback=fallback,
        required_tools={"rank_competencies", "save_interview_turn"},
    )
    if turn is not None:
        turn.timing = {"path": "live_fallback", "rank_ms": round(rank_ms, 1), "pool_miss_ms": round((time.perf_counter() - t1) * 1000, 1),
                       "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
    return turn


async def _disabled():
    raise RuntimeError("LLM orchestration disabled for this call")


async def evaluate_hr_answer(turn: InterviewTurn) -> dict:
    """Neutral, job-relevant observations for a human reviewer. Never a score, never evidence, never a recommendation."""
    from app.services.interviews.hr import HR_SYSTEM, HRObservation, sanitize

    obs = await get_ai_gateway().generate_structured(
        f"TOPIC: {turn.category}\nQUESTION: {turn.question_text}\n\nCANDIDATE ANSWER:\n{(turn.student_answer_text or '')[:4000]}",
        HRObservation, system=HR_SYSTEM, temperature=0.0, task_type="hr_observation", related_entity_type="interview_turn",
        related_entity_id=turn.id)
    return sanitize(obs)


async def evaluate_turn_answer(turn: InterviewTurn) -> RubricEvaluation:
    from app.agents.orchestrator import job_context
    from app.core.database import AsyncSessionLocal
    from app.models.interviews import Interview

    async with AsyncSessionLocal() as _db:  # compact job context for the evaluator: role, requirements, round (no candidate history)
        itv = await _db.get(Interview, turn.interview_id)
        ctx = await job_context(_db, itv.job_id, stage_type=itv.stage_type) if itv else None
    rubric = {
        "job_context": ctx,
        "question": turn.question_text,
        "difficulty": turn.difficulty,
        "criteria": [
            "Technical accuracy of the concepts used",
            "Depth of reasoning",
            "Completeness relative to the question",
            "Clarity of communication",
        ],
        "version": "interview_rubric_v1",
    }
    return await get_ai_gateway().evaluate_rubric(
        turn.student_answer_text or "", rubric, RubricEvaluation, task_type="interview_rubric_evaluation",
        related_entity_type="interview_turn", related_entity_id=turn.id,
    )
