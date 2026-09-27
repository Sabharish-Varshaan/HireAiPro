import uuid

from pydantic import BaseModel

from app.models.enums import QuestionSourceType, QuestionStatus, QuestionType, Visibility


class QuestionCreate(BaseModel):
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID
    difficulty: str = "medium"
    options: list[str] | None = None
    correct_option_index: int | None = None
    expected_concepts: list[str] | None = None
    rubric: dict | None = None
    starter_code: str | None = None
    test_cases: list[dict] | None = None
    question_bank_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    visibility: Visibility = Visibility.COMPANY_PRIVATE


class QuestionOut(BaseModel):
    id: uuid.UUID
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID
    difficulty: str
    options: list | None
    expected_concepts: list[str] | None
    rubric: dict | None
    starter_code: str | None
    test_cases: list | None
    source_type: QuestionSourceType
    visibility: Visibility
    status: QuestionStatus

    class Config:
        from_attributes = True


class QuestionStudentOut(BaseModel):
    """Question view sent to students — never includes the answer key."""

    id: uuid.UUID
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID
    difficulty: str
    options: list | None
    starter_code: str | None

    class Config:
        from_attributes = True


class QuestionImportRow(BaseModel):
    question_text: str
    question_type: QuestionType
    skill_name: str
    difficulty: str = "medium"
    options: list[str] | None = None
    correct_option_index: int | None = None
    expected_concepts: list[str] | None = None
