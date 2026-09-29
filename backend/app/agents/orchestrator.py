"""Demand-based agent orchestration.

    task + facts -> required capabilities -> capability resolver -> minimal plan -> execute (only those agents) -> compact trace

The registry lists the components that actually exist in this repository. An LLM-backed capability names the *router task type* that the
existing cost-aware provider router (`ai_gateway.providers.TASK_POLICY`) maps to a provider chain; no model name is fixed here, and
fallback/timeout/retry stay owned by that router. Deterministic capabilities have no model at all. The plan carries hard caps
(steps, LLM calls, seconds); the trace stores task, agent, capability, router task type, status and latency only (no reasoning text).
"""

import time
import uuid
from dataclasses import dataclass, field

COST_RANK = {"none": 0, "cheap": 1, "standard": 2, "strong": 3}


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    capabilities: tuple[str, ...]
    supported_tasks: tuple[str, ...]
    input_types: tuple[str, ...]
    output_schema: str
    cost_class: str = "none"
    latency_class: str = "instant"
    requires_llm: bool = False
    requires_vector_search: bool = False
    requires_audio: bool = False
    requires_code_execution: bool = False
    router_task_type: str | None = None  # key into ai_gateway.providers.TASK_POLICY; the router picks preferred and fallback models


REGISTRY: dict[str, AgentSpec] = {s.agent_id: s for s in [
    # ---- deterministic components (no model)
    AgentSpec("mcq_checker", ("deterministic_answer_check",), ("score_mcq",), ("selected_option",), "AnswerResult"),
    AgentSpec("coding_evaluator", ("code_execution", "code_correctness", "test_result_analysis"), ("score_coding",), ("source_code", "test_results"),
              "CodingScore", latency_class="seconds", requires_code_execution=True),
    AgentSpec("depth_planner", ("question_selection", "interview_state"), ("interview_next_question",), ("interview_turns", "blueprint"), "Pick"),
    AgentSpec("hr_selector", ("question_selection", "interview_state"), ("interview_next_question_hr",), ("interview_turns", "categories"), "Question"),
    AgentSpec("matching_engine", ("requirement_matching", "score_aggregation"), ("screen_resume", "rank_candidate"), ("skill_evidence", "job_requirements"),
              "Match"),
    AgentSpec("qualification_engine", ("threshold_rule", "score_aggregation"), ("qualify_round",), ("component_scores", "threshold"), "RoundResult"),
    AgentSpec("audio_transcriber", ("speech_to_text",), ("transcribe_answer",), ("audio",), "Transcript", latency_class="seconds", requires_audio=True),
    # ---- model-backed components
    AgentSpec("resume_evidence_agent", ("resume_parsing", "resume_evidence_extraction"), ("screen_resume",), ("resume_text",), "ResumeExtraction",
              cost_class="cheap", latency_class="seconds", requires_llm=True, router_task_type="resume_extraction"),
    AgentSpec("assessment_evaluator", ("rubric_scoring", "written_answer_evaluation"), ("score_written_answer",), ("answer_text", "rubric", "job_context"),
              "RubricEvaluation", cost_class="standard", latency_class="seconds", requires_llm=True, router_task_type="rubric_evaluation"),
    AgentSpec("interview_evaluator", ("rubric_scoring", "answer_evaluation"), ("evaluate_interview_answer",), ("answer_text", "rubric", "job_context"),
              "RubricEvaluation", cost_class="standard", latency_class="seconds", requires_llm=True, router_task_type="interview_rubric_evaluation"),
    AgentSpec("hr_observer", ("answer_evaluation",), ("evaluate_hr_answer",), ("answer_text",), "HRObservation", cost_class="cheap", latency_class="seconds",
              requires_llm=True, router_task_type="hr_observation"),
    AgentSpec("interview_agent", ("question_generation", "follow_up_questioning"), ("interview_next_question_live",), ("interview_turns", "job_context"),
              "InterviewDecision", cost_class="strong", latency_class="slow", requires_llm=True, requires_vector_search=True,
              router_task_type="agent:interview_agent"),
    AgentSpec("assessment_agent", ("question_generation", "question_validation"), ("generate_questions",), ("job_context", "blueprint"), "AssessmentPlan",
              cost_class="standard", latency_class="slow", requires_llm=True, requires_vector_search=True, router_task_type="question_generation"),
    AgentSpec("career_agent", ("gap_analysis", "roadmap_generation"), ("build_roadmap",), ("student_skills", "job_requirements"), "LearningPath",
              cost_class="standard", latency_class="slow", requires_llm=True, router_task_type="agent:career_agent"),
    AgentSpec("knowledge_agent", ("knowledge_retrieval",), ("answer_knowledge_query",), ("query",), "RagAnswer", cost_class="cheap", latency_class="seconds",
              requires_llm=True, requires_vector_search=True, router_task_type="rag_answer"),
]}


@dataclass
class Step:
    agent_id: str
    capability: str
    router_task_type: str | None
    status: str = "planned"
    latency_ms: float | None = None


@dataclass
class Plan:
    task: str
    steps: list[Step] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    max_steps: int = 4
    max_llm_calls: int = 2
    timeout_seconds: float = 60.0

    @property
    def agents(self) -> list[str]:
        return list(dict.fromkeys(s.agent_id for s in self.steps))

    @property
    def uses_llm(self) -> bool:
        return any(REGISTRY[s.agent_id].requires_llm for s in self.steps)

    def uses(self, agent_id: str) -> bool:
        return agent_id in self.agents

    def as_dict(self) -> dict:
        return {"task": self.task, "agents": self.agents, "uses_llm": self.uses_llm, "skipped": self.skipped, "notes": self.notes,
                "limits": {"max_steps": self.max_steps, "max_llm_calls": self.max_llm_calls, "timeout_seconds": self.timeout_seconds}}


class PlanError(ValueError):
    pass


def required_capabilities(task: str, facts: dict) -> list[tuple[str, str]]:
    """(capability, task-supported-by) for the task, decided from the facts of THIS request only. Deterministic wherever a rule suffices."""
    if task == "score_assessment":  # facts: question_types (set of MCQ / TECHNICAL / CODING)
        qt = {str(t).split(".")[-1] for t in facts.get("question_types", ())}
        out = []
        if "MCQ" in qt:
            out.append(("deterministic_answer_check", "score_mcq"))
        if "TECHNICAL" in qt and facts.get("has_written_answers", True):
            out.append(("written_answer_evaluation", "score_written_answer"))
        if "CODING" in qt:
            out.append(("code_correctness", "score_coding"))
        return out
    if task == "score_mcq":
        return [("deterministic_answer_check", "score_mcq")]
    if task == "score_coding":
        return [("code_correctness", "score_coding")]
    if task == "screen_resume":
        return [("resume_evidence_extraction", "screen_resume"), ("requirement_matching", "screen_resume")]
    if task == "interview_next_question":  # facts: stage_type, pool_ready
        hr = facts.get("stage_type") == "HR_INTERVIEW"
        if facts.get("pool_ready", True):
            return [("question_selection", "interview_next_question_hr" if hr else "interview_next_question")]
        return [("follow_up_questioning", "interview_next_question_live")]  # controlled fallback: the pool cannot serve
    if task == "evaluate_interview_answer":  # facts: stage_type, audio
        caps = [("answer_evaluation", "evaluate_hr_answer" if facts.get("stage_type") == "HR_INTERVIEW" else "evaluate_interview_answer")]
        if facts.get("audio"):
            caps.insert(0, ("speech_to_text", "transcribe_answer"))
        return caps
    if task == "qualify_round":
        return [("threshold_rule", "qualify_round")]
    if task == "generate_questions":
        return [("question_generation", "generate_questions")]
    if task == "build_roadmap":
        return [("roadmap_generation", "build_roadmap")]
    raise PlanError(f"unknown task '{task}'")


def resolve(capability: str, supported_task: str) -> AgentSpec:
    """Cheapest registered component that provides the capability for this task (deterministic beats model-backed)."""
    cands = [a for a in REGISTRY.values() if capability in a.capabilities and (supported_task in a.supported_tasks)]
    if not cands:
        raise PlanError(f"no agent provides {capability} for {supported_task}")
    return sorted(cands, key=lambda a: (COST_RANK[a.cost_class], a.agent_id))[0]


def plan_task(task: str, **facts) -> Plan:
    """The minimal plan for this request; every registered component that is not needed is listed as skipped."""
    p = Plan(task=task)
    for cap, supported in required_capabilities(task, facts):
        a = resolve(cap, supported)
        p.steps.append(Step(agent_id=a.agent_id, capability=cap, router_task_type=a.router_task_type))
    llm_steps = sum(1 for s in p.steps if REGISTRY[s.agent_id].requires_llm)
    p.max_steps = max(1, len(p.steps))
    p.max_llm_calls = llm_steps if not facts.get("bounded_calls") else min(llm_steps, facts["bounded_calls"])
    if not p.uses_llm:
        p.notes.append("deterministic: no model is called")
    p.skipped = sorted(a for a in REGISTRY if a not in p.agents)
    if len(p.steps) > 6:
        raise PlanError("plan exceeds the maximum number of steps")
    return p


async def record_trace(db, plan: Plan, *, context_type: str | None = None, context_id: uuid.UUID | None = None, status: str = "COMPLETED",
                       used_fallback: bool = False, error: str | None = None) -> None:
    """Compact, reasoning-free execution trace in the existing agent_runs table: task, agents, capability, router task type, status, latency."""
    from app.models.misc import AgentRun

    db.add(AgentRun(agent_type="orchestrator", task=plan.task, status=status, context_type=context_type, context_id=context_id, used_fallback=used_fallback,
                    error=error, tool_calls=[{"agent": s.agent_id, "capability": s.capability, "router_task_type": s.router_task_type, "status": s.status,
                                              "latency_ms": s.latency_ms} for s in plan.steps] + [{"skipped": plan.skipped, "notes": plan.notes,
                                                                                                   "limits": plan.as_dict()["limits"]}]))


class Timer:
    """Times a plan step: `with Timer(step): ...` marks it completed or failed and stores the latency."""

    def __init__(self, step: Step):
        self.step = step

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.step.latency_ms = round((time.perf_counter() - self.t) * 1000, 1)
        self.step.status = "failed" if exc_type else "completed"
        return False


async def job_context(db, job_id: uuid.UUID, *, stage_type: str | None = None, rubric: dict | None = None) -> dict:
    """The canonical, compact context an evaluation agent receives: the role, its requirements, the current round and the rubric. It
    deliberately carries nothing about the candidate beyond what the caller adds for THIS task (no history, no personal attributes)."""
    from sqlalchemy import select

    from app.models.jobs import Job, JobSkill
    from app.models.skills import Skill
    from app.services.pipeline import stages as S

    job = await db.get(Job, job_id)
    rows = (await db.execute(select(JobSkill, Skill.canonical_name).join(Skill, Skill.id == JobSkill.skill_id)
                             .where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True)))).all()
    return {"job_id": str(job_id), "role": job.title if job else None,
            "required_skills": [n for js, n in rows if str(js.requirement_type).endswith("required")],
            "preferred_skills": [n for js, n in rows if str(js.requirement_type).endswith("preferred")],
            "experience": {"level": getattr(job, "experience_level", None), "min_years": getattr(job, "experience_min_years", None),
                           "max_years": getattr(job, "experience_max_years", None)},
            "current_round": S.label(stage_type) if stage_type else None, "rubric": rubric}
