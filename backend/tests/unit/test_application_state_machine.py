from app.models.enums import ApplicationStatus as S
from app.services.applications.state_machine import can_transition


def test_draft_can_only_go_to_applied():
    assert can_transition(S.DRAFT, S.APPLIED)
    assert not can_transition(S.DRAFT, S.SHORTLISTED)


def test_terminal_states_have_no_transitions():
    assert not can_transition(S.OFFER, S.REJECTED)
    assert not can_transition(S.REJECTED, S.APPLIED)


def test_cannot_skip_assessment_to_interview_completed():
    assert not can_transition(S.APPLIED, S.INTERVIEW_COMPLETED)


def test_full_happy_path_is_walkable():
    path = [
        S.DRAFT,
        S.APPLIED,
        S.ASSESSMENT_PENDING,
        S.ASSESSMENT_COMPLETED,
        S.INTERVIEW_PENDING,
        S.INTERVIEW_COMPLETED,
        S.UNDER_REVIEW,
        S.SHORTLISTED,
        S.OFFER,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target), f"{current} -> {target} should be allowed"


def test_rejection_reachable_from_most_active_states():
    for state in [S.APPLIED, S.ASSESSMENT_PENDING, S.INTERVIEW_PENDING, S.UNDER_REVIEW, S.SHORTLISTED]:
        assert can_transition(state, S.REJECTED)
