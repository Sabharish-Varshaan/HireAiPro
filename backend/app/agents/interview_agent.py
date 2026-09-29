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
from app.services.interviews.selector import SELECTION_WINDOW, Candidate, rank_candidates
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
    """Deterministic competency/difficulty selection, then the next question from the prepared pool (a DB lookup).
    Only when the pool cannot serve does the slower live path (agent, then single call) run. Stage times are stored."""
    from app.services.interviews.pool import select_from_pool

    t0 = time.perf_counter()
    job = await db.get(Job, interview.job_id)
    log = ToolLog()
    deps = InterviewDeps(db=db, interview=interview, job=job, log=log)
    count = len((await db.scalars(select(InterviewTurn.id).where(InterviewTurn.interview_id == interview.id))).all())
    ranked = await rank_candidates(db, job.id, interview.student_id, interview.id)
    rank_ms = (time.perf_counter() - t0) * 1000
    if not ranked or count >= interview.max_turns:
        return None

    t1 = time.perf_counter()
    picked = await select_from_pool(db, interview, ranked, SELECTION_WINDOW)
    if picked is not None:
        pq, cand = picked
        turn = InterviewTurn(
            interview_id=interview.id, turn_index=count, target_skill_id=cand.skill_id, question_text=pq.question_text,
            difficulty=pq.difficulty, reason_for_question=f"{pq.reason or 'prepared question'} [{cand.reason}]",
            transcript_meta={"source_refs": pq.source_refs} if pq.source_refs else None, pool_question_id=pq.id,
            timing={"path": "pool", "pool_source": pq.source, "rank_ms": round(rank_ms, 1),
                    "select_ms": round((time.perf_counter() - t1) * 1000, 1), "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
        db.add(turn)
        await db.flush()
        return turn
    pool_miss_ms = (time.perf_counter() - t1) * 1000

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
        turn.timing = {"path": "live_fallback", "rank_ms": round(rank_ms, 1), "pool_miss_ms": round(pool_miss_ms, 1),
                       "total_ms": round((time.perf_counter() - t0) * 1000, 1)}
    return turn


async def _disabled():
    raise RuntimeError("LLM orchestration disabled for this call")


async def evaluate_turn_answer(turn: InterviewTurn) -> RubricEvaluation:
    rubric = {
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
