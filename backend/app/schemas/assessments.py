import uuid

from pydantic import BaseModel

from app.models.enums import AssessmentAttemptStatus
from app.schemas.questions import QuestionStudentOut


class GenerateAssessmentRequest(BaseModel):
    title: str


class AssessmentOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    title: str
    status: str
    total_duration_minutes: int

    class Config:
        from_attributes = True


class AssessmentQuestionOut(BaseModel):
    id: uuid.UUID
    order_index: int
    question: QuestionStudentOut


class AssessmentSectionOut(BaseModel):
    id: uuid.UUID
    title: str
    order_index: int
    questions: list[AssessmentQuestionOut]


class AssessmentDetailOut(AssessmentOut):
    sections: list[AssessmentSectionOut] = []


class StartAttemptRequest(BaseModel):
    application_id: uuid.UUID


class AttemptOut(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    status: AssessmentAttemptStatus
    total_score: float | None

    class Config:
        from_attributes = True


class SubmitAnswerRequest(BaseModel):
    assessment_question_id: uuid.UUID
    answer_text: str | None = None
    selected_option_index: int | None = None
