import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tenancy import get_student_profile
from app.core.database import get_db
from app.models.assessments import AssessmentAnswer, AssessmentAttempt, AssessmentQuestion
from app.models.coding import CodingSubmission, CodingTestResult
from app.models.enums import AssessmentAttemptStatus, EvidenceSourceType, QuestionType, UserRole
from app.models.questions import Question
from app.models.users import User
from app.schemas.coding import CodingResultOut, CodingSubmitRequest
from app.services.coding.judge0_client import LANGUAGE_IDS, get_judge0_client
from app.services.evidence.service import record_evidence

router = APIRouter(prefix="/coding", tags=["coding"])


@router.post("/submit", response_model=CodingResultOut)
async def submit_code(payload: CodingSubmitRequest, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    """Pass/fail comes only from Judge0 comparing stdout to the stored
    expected output. No LLM is involved in grading."""
    if payload.language not in LANGUAGE_IDS:
        raise HTTPException(422, f"Unsupported language; choose one of {sorted(LANGUAGE_IDS)}")
    me = await get_student_profile(db, user)
    answer = await db.get(AssessmentAnswer, payload.assessment_answer_id) if payload.assessment_answer_id else None
    attempt = await db.get(AssessmentAttempt, answer.attempt_id) if answer else None
    if answer is None or attempt is None or me is None or attempt.student_id != me.id:
        raise HTTPException(404, "Answer not found in one of your attempts (save the answer first)")
    if attempt.status != AssessmentAttemptStatus.IN_PROGRESS:
        raise HTTPException(409, "Attempt already submitted")
    aq = await db.get(AssessmentQuestion, answer.assessment_question_id)
    question = await db.get(Question, aq.question_id)
    if question.id != payload.question_id or QuestionType(question.question_type) != QuestionType.CODING or not question.test_cases:
        raise HTTPException(422, "Not a coding question with test cases")

    submission = CodingSubmission(
        assessment_answer_id=answer.id, question_id=question.id, language=payload.language,
        source_code=payload.source_code, status="RUNNING", total_count=len(question.test_cases),
    )
    db.add(submission)
    await db.flush()
    results = await get_judge0_client().run_many(payload.source_code, payload.language, question.test_cases)

    passed = 0
    visible = []
    for idx, r in enumerate(results):
        ok = (r.get("status") or {}).get("id") == 3
        passed += ok
        db.add(CodingTestResult(
            submission_id=submission.id, test_case_index=idx, passed=ok, stdout=r.get("stdout"),
            stderr=r.get("stderr") or r.get("compile_output"),
            time_ms=float(r["time"]) * 1000 if r.get("time") else None,
            memory_kb=float(r["memory"]) if r.get("memory") else None,
            judge0_token=r.get("token"), judge0_status=(r.get("status") or {}).get("description"),
        ))
        visible.append({"index": idx, "passed": ok, "status": (r.get("status") or {}).get("description"),
                        "execution_backend": r.get("execution_backend", "judge0"), "fallback_reason": r.get("fallback_reason"),
                        "stderr": (r.get("stderr") or r.get("compile_output") or "")[:500] or None})

    submission.passed_count = passed
    submission.score = passed / submission.total_count
    submission.status = "COMPLETED"
    answer.answer_text = payload.source_code
    answer.score = submission.score * aq.points
    await record_evidence(db, attempt.student_id, question.skill_id, EvidenceSourceType.CODING, submission.score,
                          source_id=submission.id, raw_score=float(passed), difficulty=question.difficulty, confidence=0.9,
                          rubric_version="judge0_tests", idempotency_key=f"CODING:answer:{answer.id}")
    await db.commit()
    return CodingResultOut(submission_id=submission.id, status=submission.status, passed_count=passed,
                           total_count=submission.total_count, score=submission.score, tests=visible)
