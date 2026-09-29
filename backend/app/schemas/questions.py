import uuid

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import QuestionSourceType, QuestionStatus, QuestionType, Visibility


class QuestionCreate(BaseModel):
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID | None = None  # required except for APTITUDE and HR_INTERVIEW questions
    domain: str = "TECHNICAL"
    category: str | None = None
    sub_category: str | None = None
    difficulty: str = "medium"
    options: list[str] | None = None
    correct_option_index: int | None = None
    expected_concepts: list[str] | None = None
    rubric: dict | None = None
    starter_code: str | None = None
    test_cases: list[dict] | None = None
    allowed_languages: list[Literal["python", "javascript", "cpp"]] | None = None  # None = all supported
    question_bank_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    visibility: Visibility = Visibility.COMPANY_PRIVATE


class QuestionOut(BaseModel):
    id: uuid.UUID
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID | None = None
    domain: str = "TECHNICAL"
    category: str | None = None
    sub_category: str | None = None
    difficulty: str
    options: list | None
    expected_concepts: list[str] | None
    rubric: dict | None
    starter_code: str | None
    test_cases: list | None
    allowed_languages: list | None = None
    source_type: QuestionSourceType
    visibility: Visibility
    status: QuestionStatus
    organization_id: uuid.UUID | None = None
    correct_option_index: int | None = None
    source_refs: list | None = None
    validation_report: dict | None = None
    model_version: str | None = None
    skill_name: str | None = None
    provenance: str | None = None

    model_config = ConfigDict(from_attributes=True)


class QuestionStudentOut(BaseModel):
    """Question view sent to students — never includes the answer key."""

    id: uuid.UUID
    question_text: str
    question_type: QuestionType
    skill_id: uuid.UUID | None = None
    category: str | None = None
    difficulty: str
    options: list | None
    starter_code: str | None
    allowed_languages: list | None = None  # hidden test cases are never included

    model_config = ConfigDict(from_attributes=True)


class QuestionImportRow(BaseModel):
    question_text: str
    question_type: QuestionType
    skill_name: str
    difficulty: str = "medium"
    options: list[str] | None = None
    correct_option_index: int | None = None
    expected_concepts: list[str] | None = None
