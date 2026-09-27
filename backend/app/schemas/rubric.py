from pydantic import BaseModel, Field


class RubricEvaluation(BaseModel):
    concept_accuracy: float = Field(ge=0, le=1)
    reasoning: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    communication: float = Field(ge=0, le=1)
    demonstrated_concepts: list[str]
    missing_concepts: list[str]
    evaluator_confidence: float = Field(ge=0, le=1)

    @property
    def overall_score(self) -> float:
        return (
            0.4 * self.concept_accuracy
            + 0.25 * self.reasoning
            + 0.25 * self.completeness
            + 0.10 * self.communication
        )
