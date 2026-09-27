import uuid

from pydantic import BaseModel


class InterviewDecision(BaseModel):
    target_skill_id: uuid.UUID
    question_text: str
    difficulty: str
    reason_for_question: str
    should_continue: bool
