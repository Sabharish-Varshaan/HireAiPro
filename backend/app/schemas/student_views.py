"""Student-facing response schemas (docs/SCORE_VISIBILITY.md).

A STUDENT never receives raw hiring data: assessment/answer scores, interview
rubric values, match or fit percentages, evidence confidence, skill levels,
rank or proctoring review data. These schemas simply have no such fields, so a
restricted value cannot leak through DevTools — it is never serialized.
Qualitative, developmental information (strengths, skills to develop, status,
coding pass/fail status, roadmap) is allowed.
"""

import datetime as dt
import uuid

from pydantic import BaseModel

from app.models.enums import ApplicationStatus


def is_student(user) -> bool:
    from app.models.enums import UserRole

    return getattr(user, "role", None) == UserRole.STUDENT


def skill_band(level: float | None) -> str:
    """Coarse qualitative band for a student's own skill (no number)."""
    if level is None:
        return "not_yet_demonstrated"
    if level >= 0.7:
        return "strong"
    if level >= 0.4:
        return "developing"
    return "emerging"


class StudentApplicationView(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    status: ApplicationStatus
    job_title: str | None = None
    organization_name: str | None = None
    applied_at: dt.datetime | None = None
    # The stage the candidate can act on now (exact label, e.g. "Coding Assessment"), and how far along the hiring process is.
    next_stage: str | None = None
    next_stage_label: str | None = None
    next_stage_status: str | None = None
    stages_total: int | None = None
    stages_done: int | None = None


class StudentAttemptView(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    status: str
    completed: bool


class StudentAnswerView(BaseModel):
    answer_id: uuid.UUID
    assessment_question_id: uuid.UUID
    question_type: str
    answer_text: str | None = None
    selected_option_index: int | None = None
    question_text: str | None = None
    completed: bool
    coding: dict | None = None  # {"language", "status": ALL_PASSED|SOME_FAILED|NOT_RUN, "backend"}


class StudentCodingResult(BaseModel):
    submission_id: uuid.UUID
    language: str
    execution_backend: str | None = None
    result: str  # ALL_TESTS_PASSED | SOME_TESTS_FAILED | COMPILE_OR_RUNTIME_ERROR
    message: str | None = None  # first compiler/runtime error text only


class StudentInterviewTurnView(BaseModel):
    id: uuid.UUID
    turn_index: int
    skill_name: str | None = None
    question_text: str
    student_answer_text: str | None = None
    answer_source: str | None = None
    answered: bool


class StudentMatchView(BaseModel):
    """Developmental view of a completed evaluation: qualitative only."""
    application_id: uuid.UUID
    strengths: list[str]
    skills_to_develop: list[str]
    missing_skills: list[str]


class StudentSkillView(BaseModel):
    skill_id: uuid.UUID
    skill_name: str | None = None
    band: str
    evidence_count: int


class StudentEvidenceView(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    skill_name: str | None = None
    source_type: str
    created_at: dt.datetime | None = None
    counts_toward_skill: bool


class StudentGapView(BaseModel):
    skill_id: uuid.UUID
    skill_name: str
    status: str  # not_yet_demonstrated | below_requirement
    priority: int  # 1 = work on first


def coding_status(passed: int, total: int, statuses: list[str | None]) -> str:
    if total and passed == total:
        return "ALL_TESTS_PASSED"
    if any(s and ("Compilation" in s or "Runtime Error" in s) for s in statuses):
        return "COMPILE_OR_RUNTIME_ERROR"
    return "SOME_TESTS_FAILED"
