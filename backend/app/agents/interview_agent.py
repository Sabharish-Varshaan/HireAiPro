"""Interview Agent: adaptively selects the next competency to probe and
phrases a question for it. Skill selection is deterministic (see
app.services.interviews.selector); the agent's own job is turning that
decision into a concrete, well-formed question and — after an answer comes
in — scoring it against a rubric. It never sets skill proficiency directly;
that remains the SkillEstimator's job, fed by the evidence this agent
produces.
"""

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interviews import Interview, InterviewTurn
from app.schemas.interview import InterviewDecision
from app.schemas.rubric import RubricEvaluation
from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.interviews.selector import select_next_skill


class _GeneratedQuestion(BaseModel):
    question_text: str
    reason_for_question: str

QUESTION_GEN_INSTRUCTION = (
    "You are conducting a technical interview. Ask ONE clear, concrete, {difficulty}-difficulty "
    "question that tests the candidate's practical understanding of '{skill_name}'. Avoid yes/no "
    "questions. reason_for_question should be one sentence explaining why this competency needs "
    "probing right now."
)


async def decide_next_turn(
    db: AsyncSession, interview: Interview
) -> InterviewDecision | None:
    selection = await select_next_skill(db, interview.job_id, interview.student_id, interview.id)
    turn_count = len(
        (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == interview.id))).all()
    )

    if selection is None or turn_count >= interview.max_turns:
        return None

    skill_id, skill_name, difficulty = selection
    gateway = get_ai_gateway()
    prompt = QUESTION_GEN_INSTRUCTION.format(difficulty=difficulty, skill_name=skill_name)

    generated = await gateway.generate_structured(
        f"Generate the interview question now for skill '{skill_name}'.",
        _GeneratedQuestion,
        system=prompt,
    )
    return InterviewDecision(
        target_skill_id=skill_id,
        question_text=generated.question_text,
        difficulty=difficulty,
        reason_for_question=generated.reason_for_question,
        should_continue=True,
    )


async def evaluate_turn_answer(question_text: str, expected_concepts_hint: str, answer_text: str) -> RubricEvaluation:
    gateway = get_ai_gateway()
    rubric = {
        "question": question_text,
        "criteria": [
            "Technical accuracy of the concepts used",
            "Depth of reasoning",
            "Completeness relative to the question",
            "Clarity of communication",
        ],
        "hint": expected_concepts_hint,
    }
    return await gateway.evaluate_rubric(answer_text, rubric, RubricEvaluation)
