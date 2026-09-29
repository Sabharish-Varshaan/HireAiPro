"""Deterministic assessment blueprint engine.

Given confirmed job_skills, decides how many questions of which type/
difficulty each skill should get. No AI involved in this step — the
Assessment Agent only fills coverage gaps and generates missing questions
afterwards.
"""

import uuid
from dataclasses import dataclass, field


@dataclass
class SkillAllocation:
    skill_id: uuid.UUID
    skill_name: str
    weight: float
    mcq_count: int
    technical_count: int
    coding_count: int


@dataclass
class Blueprint:
    allocations: list[SkillAllocation] = field(default_factory=list)
    total_questions: int = 0
    estimated_duration_minutes: int = 0


def build_blueprint(job_skills: list[dict], target_total_questions: int = 12) -> Blueprint:
    """job_skills: list of {skill_id, skill_name, requirement_type, importance, minimum_level}"""
    if not job_skills:
        return Blueprint()

    total_importance = sum(s["importance"] for s in job_skills) or 1.0
    allocations: list[SkillAllocation] = []
    total_q = 0

    for skill in job_skills:
        weight = skill["importance"] / total_importance
        n_questions = max(1, round(weight * target_total_questions))

        # Coding gets weighted to problem-solving-flavored / high-level skills;
        # otherwise split between MCQ (breadth) and technical (depth).
        is_problem_solving = "problem solving" in skill["skill_name"].lower() or \
            "algorithm" in skill["skill_name"].lower() or \
            "data structure" in skill["skill_name"].lower()

        if is_problem_solving:
            coding = n_questions
            technical = 0
            mcq = 0
        else:
            coding = 0
            technical = max(1, round(n_questions * 0.5))
            mcq = max(0, n_questions - technical)

        allocations.append(
            SkillAllocation(
                skill_id=skill["skill_id"],
                skill_name=skill["skill_name"],
                weight=weight,
                mcq_count=mcq,
                technical_count=technical,
                coding_count=coding,
            )
        )
        total_q += mcq + technical + coding

    _ensure_breadth(allocations)
    total_q = sum(a.mcq_count + a.technical_count + a.coding_count for a in allocations)
    duration = total_q * 4  # ~4 minutes per question, deterministic heuristic
    return Blueprint(allocations=allocations, total_questions=total_q, estimated_duration_minutes=duration)


MCQ_SHARE = 0.4  # target share of multiple-choice questions among the non-coding questions
MIN_QUESTIONS_FOR_BREADTH = 4


def _ensure_breadth(allocations: list[SkillAllocation]) -> None:
    """A skill that gets a single question used to get a written one, so a typical job had no multiple-choice questions at all.
    Turn the single written questions of the LEAST important skills into MCQs (deterministic; ties by name) until MCQs are
    ~40% of the non-coding questions. Important skills keep their written question, which tests depth."""
    non_coding = sum(a.mcq_count + a.technical_count for a in allocations)
    if non_coding < MIN_QUESTIONS_FOR_BREADTH:
        return
    want = max(1, round(MCQ_SHARE * non_coding))
    have = sum(a.mcq_count for a in allocations)
    singles = sorted((a for a in allocations if a.technical_count == 1 and a.mcq_count == 0 and a.coding_count == 0),
                     key=lambda a: (a.weight, a.skill_name))
    for a in singles:
        if have >= want:
            break
        a.technical_count, a.mcq_count = 0, 1
        have += 1
