"""Deterministic competency ranking for the adaptive interview.

priority = importance × (1.2 if required else 1.0) × (1 − confidence) × 0.5^asks

- skills with confidence ≥ HIGH_CONFIDENCE_THRESHOLD are excluded (already known),
- skills asked MAX_ASKS_PER_SKILL times are excluded (no repeated drilling),
- after a weak answer (< WEAK_ANSWER) on a skill, its first prerequisite is
  injected with a boost so the next turn probes the underlying concept.

Difficulty is also deterministic: the last answer on that skill ≥ STRONG_ANSWER
steps up one level, < WEAK_ANSWER steps down; otherwise it follows the
estimated level. The Interview Agent may only pick from the top
SELECTION_WINDOW candidates — this is the boundary that prevents it from
hopping to arbitrary skills.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RequirementType, SkillRelationType
from app.models.evidence import StudentSkill
from app.models.interviews import InterviewTurn
from app.models.jobs import JobSkill
from app.models.skills import Skill, SkillRelationship

HIGH_CONFIDENCE_THRESHOLD = 0.75
MAX_ASKS_PER_SKILL = 2
STRONG_ANSWER = 0.75
WEAK_ANSWER = 0.4
SELECTION_WINDOW = 2
LEVELS = ["easy", "medium", "hard"]


@dataclass
class Candidate:
    skill_id: uuid.UUID
    skill_name: str
    priority: float
    difficulty: str
    importance: float
    confidence: float
    level: float
    asks: int
    reason: str

    def as_dict(self) -> dict:
        return {
            "skill_id": str(self.skill_id), "skill": self.skill_name, "priority": round(self.priority, 4),
            "difficulty": self.difficulty, "importance": self.importance, "confidence": round(self.confidence, 3),
            "estimated_level": round(self.level, 3), "times_asked": self.asks, "why": self.reason,
        }


def _turn_score(t: InterviewTurn) -> float | None:
    ev = t.rubric_evaluation
    if not ev:
        return None
    return 0.4 * ev["concept_accuracy"] + 0.25 * ev["reasoning"] + 0.25 * ev["completeness"] + 0.10 * ev["communication"]


def _difficulty(level: float, last_score: float | None, last_difficulty: str | None) -> str:
    base = last_difficulty or ("hard" if level >= 0.7 else "easy" if level <= 0.3 else "medium")
    idx = LEVELS.index(base) if base in LEVELS else 1
    if last_score is not None:
        if last_score >= STRONG_ANSWER:
            idx = min(idx + 1, 2)
        elif last_score < WEAK_ANSWER:
            idx = max(idx - 1, 0)
    return LEVELS[idx]


async def rank_candidates(
    db: AsyncSession, job_id: uuid.UUID, student_id: uuid.UUID, interview_id: uuid.UUID
) -> list[Candidate]:
    job_skills = (
        await db.scalars(
            select(JobSkill).where(JobSkill.job_id == job_id, JobSkill.confirmed.is_(True), JobSkill.skill_id.is_not(None))
        )
    ).all()
    turns = (
        await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview_id).order_by(InterviewTurn.turn_index))
    ).all()
    student_skills = {
        s.skill_id: s for s in (await db.scalars(select(StudentSkill).where(StudentSkill.student_id == student_id))).all()
    }

    asks: dict[uuid.UUID, int] = {}
    last: dict[uuid.UUID, InterviewTurn] = {}
    for t in turns:
        asks[t.target_skill_id] = asks.get(t.target_skill_id, 0) + 1
        last[t.target_skill_id] = t

    out: list[Candidate] = []
    for js in job_skills:
        cur = student_skills.get(js.skill_id)
        conf = cur.confidence if cur else 0.0
        level = cur.estimated_level if cur else 0.0
        n = asks.get(js.skill_id, 0)
        if conf >= HIGH_CONFIDENCE_THRESHOLD or n >= MAX_ASKS_PER_SKILL:
            continue
        required = RequirementType(js.requirement_type) == RequirementType.REQUIRED
        pr = js.importance * (1.2 if required else 1.0) * (1 - conf) * (0.5 ** n)
        lt = last.get(js.skill_id)
        skill = await db.get(Skill, js.skill_id)
        out.append(Candidate(
            skill_id=js.skill_id, skill_name=skill.canonical_name if skill else js.raw_skill_name, priority=pr,
            difficulty=_difficulty(level, _turn_score(lt) if lt else None, lt.difficulty if lt else None),
            importance=js.importance, confidence=conf, level=level, asks=n,
            reason=f"{'required' if required else 'preferred'}, importance {js.importance}, confidence {conf:.2f}, asked {n}x",
        ))

    # Weak-answer prerequisite probe (only once per prerequisite).
    if turns:
        lt = turns[-1]
        score = _turn_score(lt)
        if score is not None and score < WEAK_ANSWER:
            prereq = await db.scalar(
                select(SkillRelationship.from_skill_id).where(
                    SkillRelationship.to_skill_id == lt.target_skill_id,
                    SkillRelationship.relation_type == SkillRelationType.PREREQUISITE_OF,
                )
            )
            if prereq and asks.get(prereq, 0) == 0 and all(c.skill_id != prereq for c in out):
                skill = await db.get(Skill, prereq)
                parent = next((c for c in out if c.skill_id == lt.target_skill_id), None)
                out.append(Candidate(
                    skill_id=prereq, skill_name=skill.canonical_name, priority=(parent.priority if parent else 1.0) * 1.5 + 0.01,
                    difficulty="easy", importance=parent.importance if parent else 0.5, confidence=0.0, level=0.0, asks=0,
                    reason=f"prerequisite probe after weak answer on {lt.target_skill_id}",
                ))

    out.sort(key=lambda c: c.priority, reverse=True)
    return out


async def select_next_skill(
    db: AsyncSession, job_id: uuid.UUID, student_id: uuid.UUID, interview_id: uuid.UUID
) -> tuple[uuid.UUID, str, str] | None:
    ranked = await rank_candidates(db, job_id, student_id, interview_id)
    if not ranked:
        return None
    top = ranked[0]
    return top.skill_id, top.skill_name, top.difficulty
