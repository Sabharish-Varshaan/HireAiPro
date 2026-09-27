import uuid

from pydantic import BaseModel, Field

from app.models.enums import QuestionType


class GeneratedMCQ(BaseModel):
    question_text: str
    options: list[str] = Field(min_length=3, max_length=6)
    correct_option_index: int
    explanation: str


class GeneratedTechnicalQuestion(BaseModel):
    question_text: str
    expected_concepts: list[str] = Field(min_length=2)
    rubric_criteria: list[str] = Field(min_length=2)


class GeneratedCodingQuestion(BaseModel):
    question_text: str
    starter_code: str
    test_cases: list[dict] = Field(min_length=2)


class AssessmentSectionPlan(BaseModel):
    skill_id: uuid.UUID
    skill_name: str
    question_ids: list[uuid.UUID]


class AssessmentPlan(BaseModel):
    job_id: uuid.UUID
    sections: list[AssessmentSectionPlan]
    total_questions: int
    covered_skills: list[uuid.UUID]
    missing_coverage: list[uuid.UUID]
    estimated_duration_minutes: int
