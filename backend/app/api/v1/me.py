"""The signed-in user's own data: notifications and privacy controls."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.tenancy import get_student_profile
from app.core.database import get_db
from app.models.applications import Application
from app.models.documents import Document
from app.models.enums import EvidenceSourceType, UserRole
from app.models.evidence import SkillEvidence, StudentSkill
from app.models.interviews import Interview, InterviewTurn
from app.models.misc import Notification
from app.models.skills import Skill
from app.models.users import User
from app.services.audit import audit
from app.services.evidence.estimator import recalculate_all_skills_for_student
from app.services.storage.service import get_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/notifications")
async def notifications(unread_only: bool = False, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = (await db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100))).all()
    return [{"id": n.id, "event_type": n.event_type, "title": n.title, "body": n.body, "link": n.link, "read": n.read,
             "created_at": n.created_at} for n in rows]


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read = True
    await db.commit()
    return {"read": True}


@router.post("/notifications/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    await db.commit()
    return {"read": True}


@router.get("/data")
async def my_data(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    """Everything stored about the student, in one export."""
    me = await get_student_profile(db, user)
    if me is None:
        return {"profile": None}
    names = {s.id: s.canonical_name for s in (await db.scalars(select(Skill))).all()}
    docs = (await db.scalars(select(Document).where(Document.owner_user_id == user.id))).all()
    evidence = (await db.scalars(select(SkillEvidence).where(SkillEvidence.student_id == me.id, SkillEvidence.is_deleted.is_(False)))).all()
    skills = (await db.scalars(select(StudentSkill).where(StudentSkill.student_id == me.id))).all()
    interviews = (await db.scalars(select(Interview).where(Interview.student_id == me.id))).all()
    turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id.in_([i.id for i in interviews])))).all()
    apps = (await db.scalars(select(Application).where(Application.student_id == me.id))).all()
    return {
        "account": {"email": user.email, "full_name": user.full_name, "created_at": user.created_at},
        "profile": {"headline": me.headline, "bio": me.bio, "location": me.location, "resume_status": me.resume_parse_status},
        "documents": [{"id": d.id, "type": d.doc_type, "filename": d.filename, "size_bytes": d.size_bytes, "uploaded_at": d.created_at}
                      for d in docs],
        "skill_estimates": [{"skill": names.get(s.skill_id), "level": s.estimated_level, "confidence": s.confidence} for s in skills],
        "evidence": [{"skill": names.get(e.skill_id), "source_type": e.source_type, "score": e.normalized_score,
                      "confidence": e.confidence, "created_at": e.created_at} for e in evidence],
        "interview_transcripts": [{"interview_id": t.interview_id, "question": t.question_text, "answer": t.student_answer_text,
                                   "answer_source": t.answer_source, "has_audio": t.audio_document_id is not None} for t in turns],
        "applications": [{"id": a.id, "job_id": a.job_id, "status": a.status, "created_at": a.created_at} for a in apps],
    }


def _delete_file(doc: Document) -> None:
    try:
        get_storage_service().backend.path_for(doc.storage_key).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not delete stored file %s", doc.storage_key, exc_info=True)


@router.delete("/resume")
async def delete_resume(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    """Deletes stored resume files and removes the resume-claim evidence
    derived from them. Verified evidence from assessments is unaffected
    (resume claims never counted toward scores anyway)."""
    me = await get_student_profile(db, user)
    docs = (await db.scalars(select(Document).where(Document.owner_user_id == user.id, Document.doc_type == "RESUME"))).all()
    await db.execute(update(SkillEvidence).where(SkillEvidence.student_id == me.id,
                                                 SkillEvidence.source_type == EvidenceSourceType.RESUME_CLAIM.value)
                     .values(is_deleted=True))
    if me:
        me.resume_document_id = None
        me.resume_parse_status = "PENDING"
    for d in docs:
        _delete_file(d)
        await db.delete(d)
    await audit(db, user, "privacy_resume_deleted", "student", me.id if me else None, metadata={"documents": len(docs)})
    await db.commit()
    return {"deleted_documents": len(docs)}


@router.delete("/interview-data")
async def delete_interview_data(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    """Deletes interview audio and transcript text. The rubric scores and
    evidence derived from them are kept (they're what recruiters were shown);
    the raw words are gone."""
    me = await get_student_profile(db, user)
    interviews = (await db.scalars(select(Interview).where(Interview.student_id == me.id))).all()
    turns = (await db.scalars(select(InterviewTurn).where(InterviewTurn.interview_id.in_([i.id for i in interviews])))).all()
    audio_ids = [t.audio_document_id for t in turns if t.audio_document_id]
    for t in turns:
        if t.student_answer_text is not None:
            t.student_answer_text = "[deleted by student]"
        t.audio_document_id = None
        if t.transcript_meta:
            t.transcript_meta = {k: v for k, v in t.transcript_meta.items() if k != "transcription"}
        if t.rubric_evaluation:
            t.rubric_evaluation = {k: v for k, v in t.rubric_evaluation.items()
                                   if k not in ("demonstrated_concepts", "missing_concepts")}
    await db.flush()
    for d in (await db.scalars(select(Document).where(Document.id.in_(audio_ids)))).all():
        _delete_file(d)
        await db.delete(d)
    await audit(db, user, "privacy_interview_data_deleted", "student", me.id, metadata={"turns": len(turns), "audio": len(audio_ids)})
    await db.commit()
    return {"turns_redacted": len(turns), "audio_deleted": len(audio_ids)}


@router.delete("/evidence")
async def delete_evidence(user: User = Depends(require_roles(UserRole.STUDENT)), db: AsyncSession = Depends(get_db)):
    """Soft-deletes all evidence and recalculates, which clears the profile."""
    me = await get_student_profile(db, user)
    await db.execute(update(SkillEvidence).where(SkillEvidence.student_id == me.id).values(is_deleted=True))
    await db.commit()
    await recalculate_all_skills_for_student(db, me.id, user.id, "student_deleted_evidence")
    return {"deleted": True}


@router.delete("/account")
async def deactivate_account(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Logical deletion: the account can no longer sign in and personal
    identifiers are replaced. Rows referenced by other tenants' records
    (applications, audit trail) are kept but de-identified."""
    user.is_active = False
    user.full_name = "Deleted user"
    user.email = f"deleted-{user.id}@invalid"
    await audit(db, user, "privacy_account_deactivated", "user", user.id)
    await db.commit()
    return {"deactivated": True}
