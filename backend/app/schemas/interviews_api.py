import uuid

from pydantic import BaseModel


class StartInterviewRequest(BaseModel):
    application_id: uuid.UUID


class InterviewOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    status: str

    class Config:
        from_attributes = True


class InterviewTurnOut(BaseModel):
    id: uuid.UUID
    turn_index: int
    target_skill_id: uuid.UUID
    question_text: str
    difficulty: str
    reason_for_question: str | None
    student_answer_text: str | None

    class Config:
        from_attributes = True


class AnswerTurnRequest(BaseModel):
    answer_text: str
