import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.assessments import AssessmentAnswer, AssessmentQuestion
from app.models.coding import CodingSubmission, CodingTestResult
from app.models.enums import EvidenceSourceType, UserRole
from app.models.questions import Question
from app.models.users import User
from app.schemas.coding import CodingResultOut, CodingSubmitRequest
from app.services.coding.judge0_client import get_judge0_client
from app.services.evidence.service import record_evidence

router = APIRouter(prefix="/coding", tags=["coding"])


@router.post("/submit", response_model=CodingResultOut)
async def submit_code(
    payload: CodingSubmitRequest,
    user: User = Depends(require_roles(UserRole.STUDENT)),
    db: AsyncSession = Depends(get_db),
):
    question = await db.get(Question, payload.question_id)
    if question is None or not question.test_cases:
        raise HTTPException(404, "Coding question or test cases not found")

    submission = CodingSubmission(
        assessment_answer_id=payload.assessment_answer_id,
        question_id=question.id,
        language=payload.language,
        source_code=payload.source_code,
        status="RUNNING",
        total_count=len(question.test_cases),
    )
    db.add(submission)
    await db.flush()

    client = get_judge0_client()
    results = await client.run_many(payload.source_code, payload.language, question.test_cases)

    passed = 0
    for idx, result in enumerate(results):
        is_passed = result.get("status", {}).get("id") == 3
        if is_passed:
            passed += 1
        db.add(
            CodingTestResult(
                submission_id=submission.id,
                test_case_index=idx,
                passed=is_passed,
                stdout=result.get("stdout"),
                stderr=result.get("stderr") or result.get("compile_output"),
                time_ms=float(result["time"]) * 1000 if result.get("time") else None,
                memory_kb=float(result["memory"]) if result.get("memory") else None,
                judge0_token=result.get("token"),
                judge0_status=result.get("status", {}).get("description"),
            )
        )

    submission.passed_count = passed
    submission.score = passed / submission.total_count if submission.total_count else 0.0
    submission.status = "COMPLETED"

    if payload.assessment_answer_id:
        answer = await db.get(AssessmentAnswer, payload.assessment_answer_id)
        if answer:
            answer.score = submission.score
            aq = await db.get(AssessmentQuestion, answer.assessment_question_id)
            attempt_student_id = None
            if aq:
                from app.models.assessments import AssessmentAttempt

                attempt = await db.get(AssessmentAttempt, answer.attempt_id)
                attempt_student_id = attempt.student_id if attempt else None
            if attempt_student_id:
                await record_evidence(
                    db,
                    student_id=attempt_student_id,
                    skill_id=question.skill_id,
                    source_type=EvidenceSourceType.CODING,
                    normalized_score=submission.score,
                    source_id=submission.id,
                    difficulty=question.difficulty,
                    confidence=0.9,
                )

    await db.commit()
    await db.refresh(submission)
    return CodingResultOut(
        submission_id=submission.id,
        status=submission.status,
        passed_count=submission.passed_count,
        total_count=submission.total_count,
        score=submission.score,
    )
