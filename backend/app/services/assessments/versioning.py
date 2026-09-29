"""Frozen assessment versions, per-attempt layout and the server clock.

Nothing here calls a model. `content` holds answer keys and hidden coding tests, so it never leaves the server;
`student_question` is the only projection sent to candidates.
"""

import datetime as dt
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessments import (Assessment, AssessmentAttempt, AssessmentQuestion, AssessmentSection,
                                    AssessmentVersion)
from app.models.enums import QuestionSourceType
from app.models.questions import Question

DEFAULT_CONFIG = {"duration_minutes": None, "randomize_questions": True, "randomize_options": True}
MIN_MINUTES, MAX_MINUTES = 5, 240
GRACE_SECONDS = 15  # network slack for the last autosave before the hard stop


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def effective_config(assessment: Assessment) -> dict:
    cfg = {**DEFAULT_CONFIG, **(assessment.config or {})}
    cfg["duration_minutes"] = int(cfg["duration_minutes"] or assessment.total_duration_minutes or 60)
    return cfg


def _q_json(q: Question) -> dict:
    return {"id": str(q.id), "question_text": q.question_text, "question_type": str(q.question_type), "skill_id": str(q.skill_id),
            "difficulty": q.difficulty, "options": q.options, "correct_option_index": q.correct_option_index,
            "expected_concepts": q.expected_concepts, "rubric": q.rubric, "starter_code": q.starter_code,
            "test_cases": q.test_cases, "allowed_languages": q.allowed_languages, "source_type": str(q.source_type)}


async def ensure_version(db: AsyncSession, assessment: Assessment, published_by: uuid.UUID | None = None) -> AssessmentVersion:
    """Latest version, snapshotting the live rows the first time (publish, or first candidate start for legacy rows)."""
    latest = await db.scalar(select(AssessmentVersion).where(AssessmentVersion.assessment_id == assessment.id)
                             .order_by(AssessmentVersion.version_no.desc()))
    if latest is not None:
        return latest
    sections = (await db.scalars(select(AssessmentSection).where(AssessmentSection.assessment_id == assessment.id)
                                 .order_by(AssessmentSection.order_index))).all()
    content = {"sections": []}
    for sec in sections:
        aqs = (await db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.section_id == sec.id)
                                .order_by(AssessmentQuestion.order_index))).all()
        content["sections"].append({"id": str(sec.id), "title": sec.title, "order_index": sec.order_index, "questions": [
            {"aq_id": str(aq.id), "order_index": aq.order_index, "points": aq.points,
             "question": _q_json(await db.get(Question, aq.question_id))} for aq in aqs]})
    cfg = effective_config(assessment)
    v = AssessmentVersion(assessment_id=assessment.id, version_no=1, duration_minutes=cfg["duration_minutes"], config=cfg, content=content,
                          content_hash=hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest(), published_by=published_by)
    db.add(v)
    await db.flush()
    return v


@dataclass
class FrozenQ:
    aq_id: uuid.UUID
    section_id: uuid.UUID
    order_index: int
    points: float
    id: uuid.UUID
    question_text: str
    question_type: str
    skill_id: uuid.UUID
    difficulty: str
    options: list | None
    correct_option_index: int | None
    expected_concepts: list | None
    rubric: dict | None
    starter_code: str | None
    test_cases: list | None
    allowed_languages: list | None
    source_type: str


@dataclass
class Frozen:
    sections: list[dict] = field(default_factory=list)  # [{id, title, order_index, aq_ids}]
    by_aq: dict[uuid.UUID, FrozenQ] = field(default_factory=dict)


def _from_content(content: dict) -> Frozen:
    fz = Frozen()
    for sec in content["sections"]:
        ids = []
        for item in sec["questions"]:
            q = item["question"]
            fq = FrozenQ(aq_id=uuid.UUID(item["aq_id"]), section_id=uuid.UUID(sec["id"]), order_index=item["order_index"],
                         points=item["points"], id=uuid.UUID(q["id"]), question_text=q["question_text"], question_type=q["question_type"],
                         skill_id=uuid.UUID(q["skill_id"]), difficulty=q["difficulty"], options=q["options"],
                         correct_option_index=q["correct_option_index"], expected_concepts=q["expected_concepts"], rubric=q["rubric"],
                         starter_code=q["starter_code"], test_cases=q["test_cases"], allowed_languages=q["allowed_languages"],
                         source_type=q["source_type"])
            fz.by_aq[fq.aq_id] = fq
            ids.append(fq.aq_id)
        fz.sections.append({"id": uuid.UUID(sec["id"]), "title": sec["title"], "order_index": sec["order_index"], "aq_ids": ids})
    return fz


async def load_frozen(db: AsyncSession, attempt: AssessmentAttempt) -> Frozen:
    if attempt.version_id is None:  # attempt predates versioning: fall back to the live rows
        assessment = await db.get(Assessment, attempt.assessment_id)
        v = await ensure_version(db, assessment)
    else:
        v = await db.get(AssessmentVersion, attempt.version_id)
    return _from_content(v.content)


def new_layout(fz: Frozen, cfg: dict) -> tuple[dict, dict]:
    """Per-attempt question order (within each section) and option permutations, from a CSPRNG, persisted once."""
    rng = secrets.SystemRandom()
    qorder, oorder = {}, {}
    for sec in fz.sections:
        ids = list(sec["aq_ids"])
        if cfg.get("randomize_questions"):
            rng.shuffle(ids)
        qorder[str(sec["id"])] = [str(i) for i in ids]
    for aq_id, q in fz.by_aq.items():
        if q.question_type == "MCQ" and q.options:
            perm = list(range(len(q.options)))
            if cfg.get("randomize_options"):
                rng.shuffle(perm)
            oorder[str(aq_id)] = perm
    return qorder, oorder


def to_original(attempt: AssessmentAttempt, aq_id, displayed: int | None) -> int | None:
    perm = (attempt.option_orders or {}).get(str(aq_id))
    if displayed is None or perm is None:
        return displayed
    if not 0 <= displayed < len(perm):
        raise ValueError("option index out of range")
    return perm[displayed]


def to_displayed(attempt: AssessmentAttempt, aq_id, original: int | None) -> int | None:
    perm = (attempt.option_orders or {}).get(str(aq_id))
    if original is None or perm is None:
        return original
    return perm.index(original) if original in perm else None


def student_question(attempt: AssessmentAttempt, q: FrozenQ) -> dict:
    """Candidate projection: no key, no rubric, no test cases; options in this attempt's order."""
    perm = (attempt.option_orders or {}).get(str(q.aq_id))
    options = [q.options[i] for i in perm] if (perm and q.options) else q.options
    starter = None if q.source_type == QuestionSourceType.AI_GENERATED.value else q.starter_code
    out = {"id": q.id, "question_text": q.question_text, "question_type": q.question_type, "skill_id": q.skill_id,
           "difficulty": q.difficulty, "options": options, "starter_code": starter, "allowed_languages": q.allowed_languages}
    if q.question_type == "CODING" and q.test_cases:
        from app.services.coding import test_model as tm

        out["sample_tests"] = tm.sample_view(q.test_cases)  # visible samples only; hidden inputs/outputs never leave the server
        out["hidden_test_count"] = tm.hidden_count(q.test_cases)
    return out


def expired(attempt: AssessmentAttempt, grace: bool = False) -> bool:
    if attempt.expires_at is None:
        return False
    return now() > attempt.expires_at + (dt.timedelta(seconds=GRACE_SECONDS) if grace else dt.timedelta())
