import uuid

from pydantic import BaseModel


class CodingSubmitRequest(BaseModel):
    assessment_answer_id: uuid.UUID | None = None
    question_id: uuid.UUID
    language: str
    source_code: str


class CodingResultOut(BaseModel):
    submission_id: uuid.UUID
    status: str
    passed_count: int
    total_count: int
    score: float | None
