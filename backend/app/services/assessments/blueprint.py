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

    duration = total_q * 4  # ~4 minutes per question, deterministic heuristic
    return Blueprint(allocations=allocations, total_questions=total_q, estimated_duration_minutes=duration)
