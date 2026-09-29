"""HR interview: separate selection and evaluation. No skill evidence, no numeric score, no personality/emotion/honesty inference.

Selection is a plain rotation over the configured categories. Evaluation produces neutral, job-relevant observations only; any
observation that mentions a sensitive topic (for example something the candidate volunteered) is discarded before storage."""

from pydantic import BaseModel, Field

from app.services.interviews.hr_safety import clean_observation


class HRObservation(BaseModel):
    summary: str = Field(default="", description="One or two neutral sentences describing what the candidate said that is relevant to the question")
    key_points: list[str] = Field(default_factory=list, description="Up to five short factual points, e.g. an example given, availability, preference")
    gave_concrete_example: bool = False
    addressed_question: bool = True


HR_SYSTEM = (
    "You record neutral, job-relevant notes about an interview answer for a human reviewer. Describe only what the candidate said about the topic "
    "asked. Never rate the person, never infer personality, emotion, honesty, mental state or culture fit, never guess protected characteristics, "
    "and never recommend hiring or rejecting. If the answer contains personal information unrelated to the job, leave it out."
)


def pick_hr_question(rows: list, categories: list[str], asked_categories: list[str], seen_texts: set[str]):
    """The unseen question from the category that has been asked least so far (ties by configured order). None when nothing is left."""
    counts = {c: asked_categories.count(c) for c in categories}
    order = sorted(range(len(categories)), key=lambda i: (counts[categories[i]], i))
    src_rank = {"question_bank": 0, "posting": 1, "platform_hr": 2, "generated": 3}
    for i in order:
        cat = categories[i]
        mine = [r for r in rows if r.category == cat and " ".join(r.question_text.lower().split()) not in seen_texts]
        if mine:
            mine.sort(key=lambda r: (src_rank.get(r.source, 4), r.question_text))
            return mine[0]
    return None


def sanitize(obs: HRObservation) -> dict:
    return {"type": "hr_observation", "version": "hr_observation_v1", "summary": "" if clean_observation([obs.summary]) == [] else obs.summary.strip()[:600],
            "key_points": clean_observation(obs.key_points), "gave_concrete_example": obs.gave_concrete_example,
            "addressed_question": obs.addressed_question}
