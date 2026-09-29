from app.models.enums import ApplicationStatus

ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.DRAFT: {ApplicationStatus.APPLIED},
    ApplicationStatus.APPLIED: {ApplicationStatus.ASSESSMENT_PENDING, ApplicationStatus.INTERVIEW_PENDING, ApplicationStatus.REJECTED},  # INTERVIEW_PENDING: pipelines without assessment stages
    ApplicationStatus.ASSESSMENT_PENDING: {ApplicationStatus.ASSESSMENT_COMPLETED, ApplicationStatus.REJECTED},
    ApplicationStatus.ASSESSMENT_COMPLETED: {ApplicationStatus.INTERVIEW_PENDING, ApplicationStatus.REJECTED, ApplicationStatus.UNDER_REVIEW},
    ApplicationStatus.INTERVIEW_PENDING: {ApplicationStatus.INTERVIEW_COMPLETED, ApplicationStatus.REJECTED},
    ApplicationStatus.INTERVIEW_COMPLETED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.REJECTED},
    ApplicationStatus.UNDER_REVIEW: {ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED, ApplicationStatus.ASSESSMENT_PENDING, ApplicationStatus.INTERVIEW_PENDING},  # the last two: a recruiter advance resumes the pipeline
    ApplicationStatus.SHORTLISTED: {ApplicationStatus.OFFER, ApplicationStatus.REJECTED},
    ApplicationStatus.OFFER: set(),
    ApplicationStatus.REJECTED: set(),
}


def can_transition(current: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
