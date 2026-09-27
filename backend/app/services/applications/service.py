"""Every application status change goes through `transition_application`:
validated against the state machine, written to
application_status_history, audited, and notified to the student."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import Application, ApplicationStatusHistory
from app.models.enums import ApplicationStatus
from app.models.jobs import Job
from app.models.students import StudentProfile
from app.services.applications.state_machine import can_transition
from app.services.audit import audit
from app.services.notifications import APPLICATION_STATUS_MESSAGES, notify


class InvalidTransition(Exception):
    pass


# Recruiters may only make these decisions; all other transitions are
# driven by the student's own actions (starting/finishing an assessment or
# interview) through the system.
RECRUITER_DECISIONS = {
    ApplicationStatus.ASSESSMENT_PENDING,
    ApplicationStatus.UNDER_REVIEW,
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER,
}


async def transition_application(
    db: AsyncSession,
    application: Application,
    target: ApplicationStatus,
    actor_user_id: uuid.UUID | None,
    note: str | None = None,
) -> Application:
    current = ApplicationStatus(application.status)
    if current == target:
        return application  # idempotent: repeating the same event is a no-op
    if not can_transition(current, target):
        raise InvalidTransition(f"Cannot move application from {current.value} to {target.value}")

    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=current.value,
            to_status=target.value,
            changed_by_user_id=actor_user_id,
            note=note,
        )
    )
    application.status = target
    job = await db.get(Job, application.job_id)
    await audit(
        db, actor_user_id, "application_status_changed", "application", application.id,
        organization_id=job.organization_id if job else None,
        metadata={"from": current.value, "to": target.value},
    )
    if target in RECRUITER_DECISIONS and actor_user_id is not None:
        await audit(
            db, actor_user_id, "recruiter_decision", "application", application.id,
            organization_id=job.organization_id if job else None, metadata={"decision": target.value},
        )
    profile = await db.get(StudentProfile, application.student_id)
    if profile and target.value in APPLICATION_STATUS_MESSAGES:
        event_type, title = APPLICATION_STATUS_MESSAGES[target.value]
        await notify(
            db, profile.user_id, event_type, title,
            body=f"{job.title if job else 'Your application'}: {target.value.replace('_', ' ').title()}",
            link=f"/student/applications/{application.id}",
            dedupe_key=f"app:{application.id}:{target.value}",
        )
    await db.flush()
    return application
