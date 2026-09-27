from app.core.database import AsyncSessionLocal
from app.models.questions import Question
from app.models.enums import QuestionType
from app.services.assessments.generator import generate_missing_question
from app.workers.celery_app import celery_app
from app.workers.utils import run_async


async def _bulk_generate(skill_id: str, skill_name: str, question_type: str, difficulty: str, count: int) -> dict:
    async with AsyncSessionLocal() as db:
        created = []
        for _ in range(count):
            q = await generate_missing_question(db, skill_name, QuestionType(question_type), difficulty, skill_id)
            created.append(str(q.id))
        await db.commit()
        return {"created": created}


@celery_app.task(name="questions.bulk_generate", bind=True, max_retries=2)
def bulk_generate_questions_task(
    self, skill_id: str, skill_name: str, question_type: str, difficulty: str, count: int = 3
) -> dict:
    return run_async(lambda: _bulk_generate(skill_id, skill_name, question_type, difficulty, count))
