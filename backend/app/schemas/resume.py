from pydantic import BaseModel


class ExtractedResumeSkill(BaseModel):
    skill_name: str
    evidence_text: str
    confidence: float


class ExtractedResume(BaseModel):
    skills: list[ExtractedResumeSkill]
    summary: str
