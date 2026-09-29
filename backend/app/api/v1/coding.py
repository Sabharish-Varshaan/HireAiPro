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
from app.schemas.coding import CodingSubmitRequest
from app.schemas.student_views import StudentCodingResult, coding_status
from app.services.assessments import versioning as ver
from app.services.coding.judge0_client import ExecutionUnavailable, get_judge0_client
from app.services.coding.languages import SUPPORTED_LANGUAGES, allowed_for_question, resolve_judge0_ids
from app.services.evidence.service import record_evidence

router = APIRouter(prefix="/coding", tags=["coding"])


@router.post("/submit", response_model=StudentCodingResult)
async def submit_code(payload: CodingSubmitRequest, user: User = Depends(require_roles(UserRole.STUDENT)),
                      db: AsyncSession = Depends(get_db)):
    """Pass/fail comes only from Judge0 comparing stdout to the stored
    expected output. No LLM is involved in grading."""
    if payload.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(422, f"Unsupported language; choose one of {sorted(SUPPORTED_LANGUAGES)}")
    me = await get_student_profile(db, user)
    answer = await db.get(AssessmentAnswer, payload.assessment_answer_id) if payload.assessment_answer_id else None
    attempt = await db.get(AssessmentAttempt, answer.attempt_id) if answer else None
    if answer is None or attempt is None or me is None or attempt.student_id != me.id:
        raise HTTPException(404, "Answer not found in one of your attempts (save the answer first)")
    if attempt.status != AssessmentAttemptStatus.IN_PROGRESS:
        raise HTTPException(409, "Attempt already submitted")
    if ver.expired(attempt, grace=True):
        raise HTTPException(409, {"code": "ATTEMPT_EXPIRED", "message": "Time is up; your saved code will be submitted."})
    aq = await db.get(AssessmentQuestion, answer.assessment_question_id)
    question = (await ver.load_frozen(db, attempt)).by_aq[aq.id]  # frozen content: tests cannot change mid-attempt
    if question.id != payload.question_id or QuestionType(question.question_type) != QuestionType.CODING or not question.test_cases:
        raise HTTPException(422, "Not a coding question with test cases")
    if payload.language not in allowed_for_question(question):
        raise HTTPException(422, f"This question accepts {allowed_for_question(question)}")

    submission = CodingSubmission(
        assessment_answer_id=answer.id, question_id=question.id, language=payload.language,
        source_code=payload.source_code, status="RUNNING", total_count=len(question.test_cases),
    )
    db.add(submission)
    await db.flush()
    try:
        results = await get_judge0_client().run_many(payload.source_code, payload.language, question.test_cases)
    except ExecutionUnavailable:
        await db.rollback()  # no submission row, no score, no evidence
        raise HTTPException(503, {"code": "EXECUTION_SERVICE_UNAVAILABLE",
                                  "message": "The code runner is unavailable right now. Your code is saved; please retry."})
    submission.execution_backend = ",".join(sorted({r.get("execution_backend", "judge0") for r in results}))
    submission.judge0_language_id = next((r.get("judge0_language_id") for r in results if r.get("judge0_language_id")), None)

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
                          rubric_version="judge0_tests", idempotency_key=f"CODING:attempt:{attempt.id}:aq:{aq.id}")
    await db.commit()
    # Students get a pass/fail status only: no pass counts, per-test breakdown or score
    # (docs/SCORE_VISIBILITY.md). Full results stay in coding_test_results for reviewers.
    first_error = next((v["stderr"] for v in visible if v.get("stderr")), None)
    return StudentCodingResult(
        submission_id=submission.id, language=submission.language, execution_backend=submission.execution_backend,
        result=coding_status(passed, submission.total_count, [v["status"] for v in visible]),
        message=first_error[:500] if first_error else None,
    )


@router.get("/languages")
async def coding_languages(user: User = Depends(require_roles(UserRole.STUDENT, UserRole.RECRUITER, UserRole.COMPANY_ADMIN,
                                                                 UserRole.HIRING_MANAGER, UserRole.PLATFORM_ADMIN))):
    """Supported languages with the Judge0 ids resolved from the running Judge0.
    available=false when Judge0 cannot be reached (the UI then warns before submit)."""
    try:
        live = await resolve_judge0_ids()
    except Exception:  # noqa: BLE001 — reported as available=false, not hidden
        live = {}
    return [{"id": k, "display_name": v["display_name"], "monaco": v["monaco"],
             "judge0_language_id": live.get(k, {}).get("judge0_language_id"), "judge0_name": live.get(k, {}).get("judge0_name"),
             "available": k in live} for k, v in SUPPORTED_LANGUAGES.items()]
