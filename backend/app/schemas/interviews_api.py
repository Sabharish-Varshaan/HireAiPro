import uuid

from pydantic import BaseModel, ConfigDict


class StartInterviewRequest(BaseModel):
    application_id: uuid.UUID
    stage_type: str = "TECHNICAL_INTERVIEW"  # TECHNICAL_INTERVIEW | HR_INTERVIEW


class InterviewOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    max_turns: int | None = None
    stage_type: str = "TECHNICAL_INTERVIEW"

    model_config = ConfigDict(from_attributes=True)


class InterviewTurnOut(BaseModel):
    id: uuid.UUID
    turn_index: int
    target_skill_id: uuid.UUID | None = None
    category: str | None = None
    kind: str | None = None
    layer: int | None = None
    skill_name: str | None = None
    question_text: str
    difficulty: str
    reason_for_question: str | None
    student_answer_text: str | None
    answer_source: str | None = None
    rubric_evaluation: dict | None = None
    transcript_meta: dict | None = None

    model_config = ConfigDict(from_attributes=True)
