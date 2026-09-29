"""Per-job hiring pipeline: configuration (company), publish validation and freeze, and the per-application journey (student / company /
placement officer, each with a different level of detail). Progression itself lives in app/services/pipeline."""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import assert_can_view_application, get_job_for_member, get_student_profile
from app.core.database import get_db
from app.models.applications import Application
from app.models.assessments import Assessment, AssessmentAnswer, AssessmentAttempt, AssessmentQuestion
from app.models.coding import CodingSubmission
from app.models.enums import JobStatus, UserRole
from app.models.interviews import Interview, InterviewTemplate, InterviewTurn
from app.models.jobs import Job
from app.models.misc import ProcessingJob
from app.models.pipeline import ApplicationStageProgress, HiringStage
from app.models.users import User
from app.schemas.student_views import is_student
from app.services.audit import audit
from app.services.pipeline import service as pl
from app.services.pipeline import stages as S
from app.services.pipeline.qualification import COMPONENTS, INTERVIEW_DEFAULT_WEIGHTS
from app.services.pipeline.service import stage_by_type

router = APIRouter(prefix="/hiring-pipeline", tags=["hiring-pipeline"])
RECRUITER_ROLES = (UserRole.COMPANY_ADMIN, UserRole.RECRUITER, UserRole.HIRING_MANAGER)
DIFFS = ("easy", "medium", "hard")


# ------------------------------------------------------------------ input
class StageIn(BaseModel):
    stage_type: str
    enabled: bool = True
    required: bool = True
    duration_minutes: int | None = Field(default=None, ge=5, le=180)
    question_count: int | None = Field(default=None, ge=1, le=60)
    proctored: bool = True
    config: dict | None = None
    pass_threshold: float | None = None  # 0-100 round score needed to qualify; empty = no automatic gate
    auto_qualify: bool = False
    weights: dict | None = None  # component weights in percent (see qualification.COMPONENTS)


class PipelineIn(BaseModel):
    stages: list[StageIn]


def _pct_map(d, name: str, keys: tuple | None = None) -> dict:
    if not isinstance(d, dict) or not d:
        raise S.PipelineError(f"{name} must be a non-empty mapping of name to percentage")
    out = {}
    for k, v in d.items():
        if not isinstance(k, str) or not k.strip() or len(k) > 40 or (keys and k not in keys):
            raise S.PipelineError(f"Unknown {name} entry '{k}'")
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            raise S.PipelineError(f"{name} percentages must be numbers")
        if out[k] < 0 or out[k] > 100:
            raise S.PipelineError(f"{name} percentages must be between 0 and 100")
    if abs(sum(out.values()) - 100) > 1.5:
        raise S.PipelineError(f"{name} percentages must add up to 100")
    return out


def validate_stage(s: StageIn) -> dict:
    """Per-type settings validation. Returns the cleaned config."""
    cfg = dict(s.config or {})
    t = s.stage_type
    if t not in S.ALL_STAGES:
        raise S.PipelineError(f"Unknown stage type {t}")
    clean: dict = {}
    if t == S.APTITUDE:
        clean["categories"] = _pct_map(cfg.get("categories") or {S.APTITUDE_CATEGORIES[0]: 50, S.APTITUDE_CATEGORIES[1]: 50}, "Category mix")
        if len(clean["categories"]) > 8:
            raise S.PipelineError("Choose at most eight aptitude categories")
        clean["difficulty"] = _pct_map(cfg.get("difficulty") or {"easy": 30, "medium": 50, "hard": 20}, "Difficulty mix", DIFFS)
    elif t == S.TECHNICAL:
        share = cfg.get("mcq_share", 40)
        if not isinstance(share, (int, float)) or not 0 <= share <= 100:
            raise S.PipelineError("The multiple-choice share must be between 0 and 100")
        clean["mcq_share"] = share
        clean["difficulty"] = _pct_map(cfg.get("difficulty") or {"easy": 30, "medium": 50, "hard": 20}, "Difficulty mix", DIFFS)
    elif t == S.CODING:
        langs = cfg.get("languages") or list(S.CODING_LANGUAGES)
        if not isinstance(langs, list) or not langs or any(x not in S.CODING_LANGUAGES for x in langs):
            raise S.PipelineError(f"Choose at least one language from {', '.join(S.CODING_LANGUAGES)}")
        clean["languages"] = sorted(set(langs))
        if cfg.get("difficulty", "medium") not in DIFFS:
            raise S.PipelineError("Coding difficulty must be easy, medium or hard")
        clean["difficulty"] = cfg.get("difficulty", "medium")
        if s.question_count is not None and s.question_count > 5:
            raise S.PipelineError("A coding assessment can have at most five problems")
    elif t == S.TECH_INTERVIEW:
        lo, hi = int(cfg.get("min_questions", 6)), int(cfg.get("max_questions", 10))
        if not 3 <= lo <= hi <= 12:
            raise S.PipelineError("Technical interview length must be between 3 and 12 questions")
        clean.update(min_questions=lo, max_questions=hi, max_asks_per_competency=max(2, min(5, int(cfg.get("max_asks_per_competency", 4)))))
    elif t == S.HR_INTERVIEW:
        cats = cfg.get("categories") or list(S.HR_CATEGORIES[:5]) + ["availability and logistics"]
        if not isinstance(cats, list) or not cats or any(c not in S.HR_CATEGORIES for c in cats):
            raise S.PipelineError("HR categories must come from the approved list")
        lo, hi = int(cfg.get("min_questions", 5)), int(cfg.get("max_questions", 8))
        if not 3 <= lo <= hi <= 10:
            raise S.PipelineError("HR interview length must be between 3 and 10 questions")
        clean.update(categories=list(dict.fromkeys(cats)), min_questions=lo, max_questions=hi)
    if t in (S.TECHNICAL, S.CODING):
        ids = cfg.get("skill_ids") or []
        if not isinstance(ids, list) or len(ids) > 30 or any(not isinstance(x, str) for x in ids):
            raise S.PipelineError("skill_ids must be a list of skill ids")
        clean["skill_ids"] = ids  # empty = every confirmed skill of the job
    if t in S.ASSESSMENT_STAGES:
        clean["shuffle_questions"] = bool(cfg.get("shuffle_questions", t != S.CODING))
        clean["shuffle_options"] = bool(cfg.get("shuffle_options", t != S.CODING))
    return clean


# ------------------------------------------------------------------ views
async def _readiness(db: AsyncSession, job: Job, st: HiringStage) -> dict:
    if not st.enabled:
        return {"state": "DISABLED", "detail": "Not part of this hiring process"}
    if st.status == "PUBLISHED":
        return {"state": "PUBLISHED", "detail": "Published"}
    if S.is_assessment(st.stage_type):
        n = 0
        if st.assessment_id:
            n = len((await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == st.assessment_id))).all())
        if n == 0:
            return {"state": "NEEDS_CONFIGURATION", "detail": "Generate the questions for this stage", "questions": 0}
        return {"state": "READY", "detail": f"{n} questions ready", "questions": n}
    t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job.id, InterviewTemplate.stage_type == st.stage_type))
    if t is None:
        return {"state": "NEEDS_CONFIGURATION", "detail": "Prepare the interview plan and question pool"}
    if t.status == "READY":
        return {"state": "READY", "detail": "Interview plan and question pool are ready"}
    if t.status == "PREPARING":
        return {"state": "PREPARING", "detail": "Preparing the question pool"}
    return {"state": "NEEDS_CONFIGURATION", "detail": t.error or "Preparation failed: try again"}


def _stage_out(st: HiringStage, readiness: dict, order: int) -> dict:
    return {"id": st.id, "stage_type": st.stage_type, "label": S.label(st.stage_type), "order": order, "enabled": st.enabled,
            "required": st.required, "duration_minutes": st.duration_minutes, "question_count": st.question_count, "proctored": st.proctored,
            "status": st.status, "config": st.config or {}, "assessment_id": st.assessment_id, "readiness": readiness,
            "pass_threshold": st.pass_threshold, "auto_qualify": st.auto_qualify, "weights": st.weights,
            "weight_components": list(COMPONENTS.get(st.stage_type, ())), "default_weights": INTERVIEW_DEFAULT_WEIGHTS if st.stage_type == S.TECH_INTERVIEW else None,
            "group": "assessment" if S.is_assessment(st.stage_type) else "interview"}


async def publish_issues(db: AsyncSession, job: Job, stages: list[HiringStage]) -> list[dict]:
    """Everything that blocks publishing, per enabled stage. Disabled stages are never validated."""
    from app.services.pipeline.stage_content import check_domain_mix

    issues: list[dict] = []
    enabled = [s for s in stages if s.enabled]
    if not enabled:
        return [{"stage_type": None, "message": "Enable at least one stage in the hiring process"}]
    for st in enabled:
        label = S.label(st.stage_type)
        if S.is_assessment(st.stage_type):
            n = 0
            if st.assessment_id:
                n = len((await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == st.assessment_id))).all())
            if n == 0:
                issues.append({"stage_type": st.stage_type, "message": f"{label} is enabled but has no questions. Generate its questions first."})
            else:
                bad = await check_domain_mix(db, st)
                if bad:
                    issues.append({"stage_type": st.stage_type, "message": f"{label}: {bad}"})
        elif st.stage_type == S.TECH_INTERVIEW:
            from app.services.interviews.pool import _competencies

            if not await _competencies(db, job.id):
                issues.append({"stage_type": st.stage_type, "message": f"{label} needs confirmed job requirements to build its competency blueprint."})
            else:
                t = await db.scalar(select(InterviewTemplate).where(InterviewTemplate.job_id == job.id, InterviewTemplate.stage_type == st.stage_type))
                if t is not None and t.status == "FAILED":
                    issues.append({"stage_type": st.stage_type, "message": f"{label}: the question pool could not be prepared. Rebuild it and try again."})
        elif st.stage_type == S.HR_INTERVIEW:
            if not (st.config or {}).get("categories"):
                issues.append({"stage_type": st.stage_type, "message": f"{label} needs at least one question category."})
    return issues


async def _pipeline_view(db: AsyncSession, job: Job) -> dict:
    rows = await pl.ensure_pipeline(db, job)
    out = []
    for i, st in enumerate(rows):
        out.append(_stage_out(st, await _readiness(db, job, st), i + 1))
    issues = await publish_issues(db, job, rows)
    return {"job_id": job.id, "published": any(r.status == "PUBLISHED" for r in rows), "stages": out, "issues": issues,
            "can_publish": not issues and not any(r.status == "PUBLISHED" for r in rows)}


# ------------------------------------------------------------------ company
@router.get("/jobs/{job_id}")
async def get_pipeline(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    job = await get_job_for_member(db, user, job_id)
    view = await _pipeline_view(db, job)
    await db.commit()
    return view


@router.put("/jobs/{job_id}")
async def put_pipeline(job_id: uuid.UUID, payload: PipelineIn, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    job = await get_job_for_member(db, user, job_id)
    rows = {r.stage_type: r for r in await pl.ensure_pipeline(db, job)}
    if any(r.status == "PUBLISHED" for r in rows.values()):
        raise HTTPException(409, {"code": "PIPELINE_FROZEN", "message": "The published hiring process is frozen: candidates may already be in it."})
    given = [s.stage_type for s in payload.stages]
    from app.services.pipeline import qualification as Q

    try:
        S.validate_order([t for t in given if next(s for s in payload.stages if s.stage_type == t).enabled])
        cleaned = {s.stage_type: validate_stage(s) for s in payload.stages}
        qual = {s.stage_type: Q.validate_settings(s.stage_type, s.pass_threshold, s.auto_qualify and s.enabled, s.weights) for s in payload.stages}
    except (S.PipelineError, Q.SettingsError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if not any(s.enabled for s in payload.stages):
        raise HTTPException(422, "Enable at least one stage")
    rest = [t for t in S.ALL_STAGES if t not in given]
    for idx, t in enumerate(given + rest):
        st = rows[t]
        st.order_index = idx
        s_in = next((s for s in payload.stages if s.stage_type == t), None)
        if s_in is None:
            continue
        changed = (st.enabled != s_in.enabled and s_in.enabled) or st.question_count != s_in.question_count or (st.config or {}) != cleaned[t]
        st.enabled, st.required, st.proctored = s_in.enabled, s_in.required, s_in.proctored
        st.duration_minutes = s_in.duration_minutes or st.duration_minutes
        # the technical interview's length comes from its duration unless a count is given, so an empty count must clear the old one
        st.question_count = s_in.question_count if t == S.TECH_INTERVIEW else (s_in.question_count or st.question_count)
        st.config = cleaned[t]
        st.pass_threshold, st.weights = qual[t]  # applies to candidates who finish the round from now on; earlier results keep the threshold they were judged by
        st.auto_qualify = bool(s_in.auto_qualify and st.pass_threshold is not None)
        if changed and st.status in ("READY",):
            st.status = "DRAFT"  # the prepared content no longer matches the settings
        if S.is_assessment(t) and st.assessment_id:
            a = await db.get(Assessment, st.assessment_id)
            if a is not None and a.status != "PUBLISHED":
                a.total_duration_minutes = st.duration_minutes or a.total_duration_minutes
                a.config = {**(a.config or {}), "duration_minutes": a.total_duration_minutes,
                            "randomize_questions": bool(cleaned[t].get("shuffle_questions", True)),
                            "randomize_options": bool(cleaned[t].get("shuffle_options", True)),
                            **({"allowed_languages": cleaned[t]["languages"]} if t == S.CODING else {})}
    await audit(db, user, "hiring_pipeline_updated", "job", job.id, organization_id=job.organization_id,
                metadata={"stages": [t for t in given if next(s for s in payload.stages if s.stage_type == t).enabled]})
    await db.commit()
    return await _pipeline_view(db, job)


@router.post("/jobs/{job_id}/stages/{stage_type}/generate", status_code=202)
async def generate_stage_content(job_id: uuid.UUID, stage_type: str, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    job = await get_job_for_member(db, user, job_id)
    if JobStatus(job.status) not in (JobStatus.REQUIREMENTS_CONFIRMED, JobStatus.ASSESSMENT_READY):
        raise HTTPException(409, "Confirm the job requirements before preparing the hiring process")
    await pl.ensure_pipeline(db, job)
    st = await stage_by_type(db, job.id, stage_type)
    if st is None or not st.enabled:
        raise HTTPException(409, f"{S.label(stage_type)} is not enabled")
    if st.status == "PUBLISHED":
        raise HTTPException(409, f"{S.label(stage_type)} is published and frozen")
    from app.workers.jobs import upsert_job
    from app.workers.tasks_questions import generate_stage_task

    await db.commit()
    await upsert_job(f"stage:{job.id}:{stage_type}", "stage_generation", {"job_id": str(job.id), "stage_type": stage_type})
    generate_stage_task.delay(str(job.id), stage_type, str(user.id))
    return {"status": "PROCESSING", "job_key": f"stage:{job.id}:{stage_type}"}


class QualIn(BaseModel):
    stage_type: str
    pass_threshold: float | None = None
    auto_qualify: bool = False
    weights: dict | None = None


class QualificationIn(BaseModel):
    stages: list[QualIn]


@router.put("/jobs/{job_id}/qualification")
async def set_qualification(job_id: uuid.UUID, payload: QualificationIn, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    """Pass thresholds, automatic qualification and component weights. Allowed after publishing (stage content stays frozen): the change applies to
    candidates who finish a round from now on. Earlier results keep the threshold they were judged by; re-evaluation is a separate audited action."""
    from app.services.pipeline import qualification as Q

    job = await get_job_for_member(db, user, job_id)
    rows = {r.stage_type: r for r in await pl.ensure_pipeline(db, job)}
    try:
        cleaned = {}
        for q in payload.stages:
            st = rows.get(q.stage_type)
            if st is None or not st.enabled:
                raise Q.SettingsError(f"{S.label(q.stage_type)} is not part of this hiring process")
            cleaned[q.stage_type] = Q.validate_settings(q.stage_type, q.pass_threshold, q.auto_qualify, q.weights)
    except Q.SettingsError as exc:
        raise HTTPException(422, str(exc)) from exc
    for q in payload.stages:
        st = rows[q.stage_type]
        st.pass_threshold, st.weights = cleaned[q.stage_type]
        st.auto_qualify = bool(q.auto_qualify and st.pass_threshold is not None)
    await audit(db, user, "qualification_settings_updated", "job", job.id, organization_id=job.organization_id,
                metadata={t: {"threshold": v[0], "weights": v[1]} for t, v in cleaned.items()})
    await db.commit()
    return await _pipeline_view(db, job)


@router.get("/jobs/{job_id}/generation")
async def generation_status(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    await get_job_for_member(db, user, job_id)
    rows = (await db.scalars(select(ProcessingJob).where(ProcessingJob.job_key.like(f"stage:{job_id}:%")))).all()
    return [{"stage_type": r.job_key.split(":")[-1], "status": r.status, "error": (r.error or "").split("\n")[0][:300] or None, "result": r.result} for r in rows]


@router.get("/jobs/{job_id}/analytics")
async def stage_analytics(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES, UserRole.PLATFORM_ADMIN)), db: AsyncSession = Depends(get_db)):
    """Per-stage numbers, never one blended score: assessment performance per assessment stage, interview completion and depth, HR completion."""
    from sqlalchemy import func

    job = await get_job_for_member(db, user, job_id)
    out = []
    for st in await pl.ensure_pipeline(db, job):
        if not st.enabled:
            continue
        prog = (await db.execute(select(ApplicationStageProgress.status, func.count()).join(Application, Application.id == ApplicationStageProgress.application_id)
                                 .where(ApplicationStageProgress.hiring_stage_id == st.id).group_by(ApplicationStageProgress.status))).all()
        counts = {k: v for k, v in prog}
        item = {"stage_type": st.stage_type, "label": S.label(st.stage_type), "candidates_reached": sum(v for k, v in counts.items() if k != S.LOCKED),
                "in_progress": counts.get(S.IN_PROGRESS, 0), "completed": counts.get(S.COMPLETED, 0), "waiting": counts.get(S.AVAILABLE, 0) + counts.get(S.LOCKED, 0)}
        if S.is_assessment(st.stage_type) and st.assessment_id:
            n, avg, lo, hi = (await db.execute(select(func.count(AssessmentAttempt.id), func.avg(AssessmentAttempt.total_score), func.min(AssessmentAttempt.total_score),
                                                      func.max(AssessmentAttempt.total_score)).where(AssessmentAttempt.assessment_id == st.assessment_id,
                                                                                                    AssessmentAttempt.status == "SCORED"))).one()
            item["scored_attempts"] = n
            item["average_score_pct"] = round(float(avg) * 100, 1) if avg is not None else None
            item["score_range_pct"] = [round(float(lo) * 100, 1), round(float(hi) * 100, 1)] if lo is not None else None
        elif S.is_interview(st.stage_type):
            done = (await db.scalars(select(Interview.id).join(Application, Application.id == Interview.application_id)
                                     .where(Interview.job_id == job.id, Interview.stage_type == st.stage_type, Interview.status == "COMPLETED"))).all()
            item["interviews_completed"] = len(done)
            if done:
                turns = await db.scalar(select(func.count(InterviewTurn.id)).where(InterviewTurn.interview_id.in_(done), InterviewTurn.student_answer_text.is_not(None)))
                item["average_answered_questions"] = round(turns / len(done), 1)
        out.append(item)
    return {"job_id": job.id, "stages": out}


@router.post("/jobs/{job_id}/publish")
async def publish_pipeline(job_id: uuid.UUID, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    """Validates every ENABLED stage, freezes each assessment stage (content, answer keys, hidden tests) and opens the job to applications."""
    from app.api.v1.interviews import _kick_prepare
    from app.services.assessments import versioning as ver
    from app.services.interviews.pool import upsert_template
    from app.services.jobs.posting import missing_for_publish

    job = await get_job_for_member(db, user, job_id)
    rows = await pl.ensure_pipeline(db, job)
    if any(r.status == "PUBLISHED" for r in rows):
        raise HTTPException(409, {"code": "ALREADY_PUBLISHED", "message": "This hiring process is already published."})
    if JobStatus(job.status) not in (JobStatus.REQUIREMENTS_CONFIRMED, JobStatus.ASSESSMENT_READY):
        raise HTTPException(409, "Confirm the job requirements before publishing")
    missing = missing_for_publish(job)
    if missing:
        raise HTTPException(409, {"code": "POSTING_INCOMPLETE", "missing": missing,
                                  "message": "Complete the posting details (employment type, work mode, location) before publishing."})
    issues = await publish_issues(db, job, rows)
    if issues:
        raise HTTPException(409, {"code": "PIPELINE_INCOMPLETE", "issues": issues, "message": issues[0]["message"]})
    now = dt.datetime.now(dt.timezone.utc)
    prepare: list[str] = []
    for st in [r for r in rows if r.enabled]:
        if S.is_assessment(st.stage_type):
            a = await db.get(Assessment, st.assessment_id)
            await ver.ensure_version(db, a, user.id)
            a.status = "PUBLISHED"
        else:
            await upsert_template(db, job, st.stage_type)
            prepare.append(st.stage_type)
        st.status, st.published_at = "PUBLISHED", now
    job.status = JobStatus.PUBLISHED
    if job.distribution_type == "INSTITUTION" and job.institution_approval in ("NOT_REQUIRED", "REJECTED"):
        job.institution_approval = "PENDING"
    await audit(db, user, "hiring_pipeline_published", "job", job.id, organization_id=job.organization_id,
                metadata={"stages": [r.stage_type for r in rows if r.enabled]})
    await db.commit()
    for t in prepare:
        rdy = await db.scalar(select(InterviewTemplate.status).where(InterviewTemplate.job_id == job.id, InterviewTemplate.stage_type == t))
        if rdy != "READY":
            _kick_prepare(job.id, t)
    return await _pipeline_view(db, job)


# ------------------------------------------------------------------ journeys
def _role(user: User) -> str:
    if is_student(user):
        return "student"
    if user.role in RECRUITER_ROLES or user.role == UserRole.PLATFORM_ADMIN:
        return "company"
    return "institution"


async def _stage_result(db: AsyncSession, application: Application, st: HiringStage, prog) -> dict | None:
    if prog.status == S.LOCKED or prog.status == S.AVAILABLE:
        return None
    if S.is_assessment(st.stage_type):
        attempt = await db.scalar(select(AssessmentAttempt).where(AssessmentAttempt.application_id == application.id,
                                                                  AssessmentAttempt.assessment_id == st.assessment_id))
        if attempt is None:
            return None
        total = len((await db.scalars(select(AssessmentQuestion.id).where(AssessmentQuestion.assessment_id == st.assessment_id))).all())
        answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id))).all()
        out = {"kind": "assessment", "attempt_id": attempt.id, "assessment_id": st.assessment_id, "status": attempt.status,
               "score_pct": round(attempt.total_score * 100, 1) if attempt.total_score is not None else None,
               "answered": sum(1 for a in answers if a.answer_text or a.selected_option_index is not None),
               "total_questions": total, "started_at": attempt.started_at, "submitted_at": attempt.submitted_at}
        if st.stage_type == S.CODING:
            probs = []
            for a in answers:
                sub = await db.scalar(select(CodingSubmission).where(CodingSubmission.assessment_answer_id == a.id).order_by(CodingSubmission.created_at.desc()))
                if sub is not None:
                    probs.append({"answer_id": a.id, "language": sub.language, "passed": sub.passed_count, "total": sub.total_count, "score": sub.score})
            out["problems_attempted"] = len(probs)
            out["problems"] = probs
        return out
    itv = await db.scalar(select(Interview).where(Interview.application_id == application.id, Interview.stage_type == st.stage_type))
    if itv is None:
        return None
    turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id == itv.id).order_by(InterviewTurn.turn_index))).all()
    out = {"kind": "interview", "interview_id": itv.id, "status": itv.status, "turns": len(turns),
           "answered": sum(1 for t in turns if t.student_answer_text is not None), "question_budget": itv.max_turns}
    if st.stage_type == S.HR_INTERVIEW:
        out["observations"] = [{"category": S.HR_CATEGORY_LABELS.get(t.category or "", t.category), "question": t.question_text,
                                "summary": (t.rubric_evaluation or {}).get("summary"), "key_points": (t.rubric_evaluation or {}).get("key_points", []),
                                "gave_concrete_example": (t.rubric_evaluation or {}).get("gave_concrete_example")} for t in turns if t.student_answer_text]
    else:
        from app.services.interviews import depth

        per: dict[str, dict] = {}
        for t in turns:
            key = str(t.target_skill_id)
            sc, _ = depth.turn_score(t.rubric_evaluation)
            e = per.setdefault(key, {"turns": 0, "scores": [], "max_layer": 0})
            e["turns"] += 1
            e["max_layer"] = max(e["max_layer"], t.layer or 0)
            if sc is not None:
                e["scores"].append(sc)
        from app.models.skills import Skill

        cov = []
        for k, e in per.items():
            sk = await db.get(Skill, uuid.UUID(k))
            cov.append({"competency": sk.canonical_name if sk else k, "questions": e["turns"], "deepest_layer": e["max_layer"],
                        "average_score_pct": round(100 * sum(e["scores"]) / len(e["scores"]), 1) if e["scores"] else None})
        out["competencies"] = cov
    return out


@router.get("/applications/{application_id}")
async def application_journey(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_application(db, user, application)
    rows = await pl.ensure_progress(db, application)
    await db.commit()
    role = _role(user)
    from app.services.pipeline import qualification as Q

    stages = []
    for i, (st, prog) in enumerate(rows):
        item = {"stage_id": st.id, "stage_type": st.stage_type, "label": S.label(st.stage_type), "order": i + 1, "status": prog.status,
                "kind": "assessment" if S.is_assessment(st.stage_type) else "interview", "started_at": prog.started_at,
                "completed_at": prog.completed_at}
        if role != "institution":
            item.update(duration_minutes=st.duration_minutes, required=st.required, proctored=st.proctored,
                        assessment_id=st.assessment_id if S.is_assessment(st.stage_type) else None)
        if role == "company":
            item["result"] = await _stage_result(db, application, st, prog)
        if role != "institution":
            item.update(pass_threshold=st.pass_threshold if role == "company" else None, auto_qualify=st.auto_qualify if role == "company" else None)
            nxt = rows[i + 1][0] if i + 1 < len(rows) else None
            item["round"] = Q.view(st, await Q.latest_result(db, application.id, st.id), S.label(nxt.stage_type) if nxt else None, audience=role)
        stages.append(item)
    current = next((s for s in stages if s["status"] in (S.IN_PROGRESS, S.AVAILABLE)), None)
    return {"application_id": application.id, "status": str(application.status), "stages": stages, "current": current["stage_type"] if current else None}


@router.post("/applications/{application_id}/stages/{stage_type}/skip")
async def skip_optional_stage(application_id: uuid.UUID, stage_type: str, user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    me = await get_student_profile(db, user)
    application = await db.get(Application, application_id)
    if me is None or application is None or application.student_id != me.id:
        raise HTTPException(404, "Application not found")
    st = await stage_by_type(db, application.job_id, stage_type)
    if st is None:
        raise HTTPException(404, "Stage not found")
    try:
        match_due = await pl.skip_stage(db, application, st, user.id)
    except pl.StageLocked as exc:
        raise HTTPException(409, {"code": "STAGE_LOCKED", "message": str(exc)}) from exc
    await db.commit()
    if match_due:
        from app.services.matching.engine import compute_match_for_application

        await compute_match_for_application(db, application.id)
    return {"status": "SKIPPED"}


# ------------------------------------------------------------------ qualification actions
class OverrideIn(BaseModel):
    decision: str  # ADVANCE | HOLD
    reason: str


async def _company_stage(db, user, application_id, stage_type):
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    await assert_can_view_application(db, user, application)
    stage = await stage_by_type(db, application.job_id, stage_type)
    if stage is None:
        raise HTTPException(404, "Stage not found")
    return application, stage


@router.post("/applications/{application_id}/stages/{stage_type}/override")
async def override_round(application_id: uuid.UUID, stage_type: str, payload: OverrideIn, user: User = Depends(require_roles(*RECRUITER_ROLES)),
                         db: AsyncSession = Depends(get_db)):
    """Advance or hold a candidate against the automatic result. The score, threshold and automatic decision are never edited."""
    from app.models.enums import ApplicationStatus as AS
    from app.services.applications.service import transition_application
    from app.services.pipeline import qualification as Q

    application, stage = await _company_stage(db, user, application_id, stage_type)
    try:
        rr = await Q.override(db, application, stage, actor=user, decision=payload.decision, reason=payload.reason)
    except Q.SettingsError as exc:
        raise HTTPException(409, str(exc)) from exc
    if rr.override_decision == "ADVANCED" and str(application.status) == AS.UNDER_REVIEW.value:
        rows = await pl.progress_rows(db, application.id)
        nxt = next((s for s, p in rows if p.status == S.AVAILABLE), None)
        if nxt is not None:
            await transition_application(db, application, AS.INTERVIEW_PENDING if S.is_interview(nxt.stage_type) else AS.ASSESSMENT_PENDING, user.id,
                                         "advanced by recruiter override")
    await db.commit()
    rows = await pl.progress_rows(db, application.id)
    i = next(i for i, (s, _) in enumerate(rows) if s.id == stage.id)
    return Q.view(stage, rr, S.label(rows[i + 1][0].stage_type) if i + 1 < len(rows) else None, audience="company")


@router.post("/applications/{application_id}/stages/{stage_type}/evaluate")
async def reevaluate_round(application_id: uuid.UUID, stage_type: str, user: User = Depends(require_roles(*RECRUITER_ROLES)), db: AsyncSession = Depends(get_db)):
    """Explicit, audited re-evaluation with the CURRENT settings (adds a new evaluation version; earlier ones are kept)."""
    from app.services.pipeline import qualification as Q

    application, stage = await _company_stage(db, user, application_id, stage_type)
    rows = await pl.progress_rows(db, application.id)
    prog = next((p for s, p in rows if s.id == stage.id), None)
    if prog is None or prog.status != S.COMPLETED:
        raise HTTPException(409, "Only a finished round can be evaluated")
    rr = await Q.evaluate_round(db, application, stage, actor=user, reevaluate=True)
    if Q.passes_gate(stage, rr):
        await Q.unlock_next(db, application.id, stage)
    await db.commit()
    return Q.view(stage, rr, None, audience="company")
