from app.models.enums import QuestionType
from app.services.assessments.generator import validate_question_payload


def test_mcq_requires_enough_options():
    ok, reasons = validate_question_payload(QuestionType.MCQ, None, None, ["A", "B"], 0, None)
    assert not ok
    assert any("options" in r for r in reasons)


def test_mcq_valid_payload_passes():
    ok, reasons = validate_question_payload(QuestionType.MCQ, None, None, ["A", "B", "C"], 1, None)
    assert ok
    assert reasons == []


def test_technical_requires_concepts_and_rubric():
    ok, reasons = validate_question_payload(QuestionType.TECHNICAL, None, None, None, None, None)
    assert not ok
    assert len(reasons) == 2


def test_coding_requires_two_test_cases():
    ok, reasons = validate_question_payload(QuestionType.CODING, None, None, None, None, [{"input": 1, "expected_output": 2}])
    assert not ok
