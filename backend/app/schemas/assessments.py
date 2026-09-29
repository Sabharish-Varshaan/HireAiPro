import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssessmentAttemptStatus
from app.schemas.questions import QuestionOut, QuestionStudentOut


class GenerateAssessmentRequest(BaseModel):
    title: str
    total_questions: int | None = Field(default=None, ge=6, le=30)


class AssessmentConfigIn(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=5, le=240)
    randomize_questions: bool | None = None
    randomize_options: bool | None = None


class AssessmentOut(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    title: str
    status: str
    total_duration_minutes: int
    config: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class AssessmentQuestionOut(BaseModel):
    id: uuid.UUID
    order_index: int
    question: QuestionOut | QuestionStudentOut


class AssessmentSectionOut(BaseModel):
    id: uuid.UUID
    title: str
    order_index: int
    questions: list[AssessmentQuestionOut]


class AssessmentDetailOut(AssessmentOut):
    sections: list[AssessmentSectionOut] = []
    plan: dict | None = None


class StartAttemptRequest(BaseModel):
    application_id: uuid.UUID


class AttemptOut(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    status: AssessmentAttemptStatus
    total_score: float | None

    model_config = ConfigDict(from_attributes=True)


class SubmitAnswerRequest(BaseModel):
    assessment_question_id: uuid.UUID
    answer_text: str | None = None
    selected_option_index: int | None = None
    marked_for_review: bool | None = None
