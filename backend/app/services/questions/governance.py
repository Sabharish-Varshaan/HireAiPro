"""Question lifecycle: DRAFT → VALIDATED → APPROVED → ACTIVE → RETIRED,
with REJECTED reachable from any pre-ACTIVE state.

Visibility is a separate axis from status. Nothing in this module ever
changes visibility except `promote_to_platform`, which only a PLATFORM_ADMIN
can call and which refuses company-uploaded content outright.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import QuestionSourceType, QuestionStatus as QS, UserRole, Visibility
from app.models.questions import Question
from app.models.users import User
from app.services.audit import audit

TRANSITIONS: dict[QS, set[QS]] = {
    QS.DRAFT: {QS.VALIDATED, QS.REJECTED},
    QS.VALIDATED: {QS.APPROVED, QS.REJECTED, QS.DRAFT},
    QS.APPROVED: {QS.ACTIVE, QS.REJECTED},
    QS.ACTIVE: {QS.RETIRED},
    QS.REJECTED: {QS.DRAFT},
    QS.RETIRED: set(),
}

# Statuses a question must be in to be pulled into an assessment.
USABLE_OWN_COMPANY = {QS.VALIDATED, QS.APPROVED, QS.ACTIVE}
USABLE_PLATFORM = {QS.APPROVED, QS.ACTIVE}


class GovernanceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def can_transition(current: QS, target: QS) -> bool:
    return target in TRANSITIONS.get(current, set())


def _may_manage(user: User, q: Question, member_org_ids: set[uuid.UUID]) -> bool:
    if user.role == UserRole.PLATFORM_ADMIN:
        return True
    return q.visibility == Visibility.COMPANY_PRIVATE and q.organization_id in member_org_ids


async def transition(
    db: AsyncSession, user: User, q: Question, target: QS, member_org_ids: set[uuid.UUID], reason: str | None = None
) -> Question:
    if not _may_manage(user, q, member_org_ids):
        raise GovernanceError("Not allowed to manage this question", 403)
    current = QS(q.status)
    if not can_transition(current, target):
        raise GovernanceError(f"Cannot move question from {current.value} to {target.value}")
    if target == QS.VALIDATED and not (q.validation_report or {}).get("ok"):
        raise GovernanceError("Question has not passed validation; run /validate first")
    q.status = target
    if reason:
        q.validation_report = {**(q.validation_report or {}), "status_reason": reason}
    await audit(
        db, user, f"question_{target.value.lower()}", "question", q.id,
        organization_id=q.organization_id, metadata={"from": current.value, "reason": reason},
    )
    await db.flush()
    return q


async def promote_to_platform(db: AsyncSession, user: User, q: Question) -> Question:
    if user.role != UserRole.PLATFORM_ADMIN:
        raise GovernanceError("Only a Platform Admin can publish global platform questions", 403)
    if q.source_type == QuestionSourceType.COMPANY_PRIVATE:
        raise GovernanceError("Company-uploaded questions can never be promoted to the platform bank", 403)
    if QS(q.status) not in {QS.APPROVED, QS.ACTIVE}:
        raise GovernanceError("Only APPROVED or ACTIVE questions can be promoted")
    private_refs = [r for r in (q.source_refs or []) if r.get("visibility") != Visibility.PLATFORM_PUBLIC.value]
    if private_refs:
        raise GovernanceError(
            "Question is grounded on tenant-private knowledge and cannot become global", 403
        )
    previous_org = q.organization_id
    q.visibility = Visibility.PLATFORM_PUBLIC
    q.organization_id = None
    await audit(
        db, user, "question_promoted_to_platform", "question", q.id,
        metadata={"previous_organization_id": str(previous_org) if previous_org else None},
    )
    await db.flush()
    return q
