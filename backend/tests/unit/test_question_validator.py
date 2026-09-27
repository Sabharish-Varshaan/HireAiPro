from app.models.enums import QuestionType
from app.services.questions.validator import content_hash, validate_structure


def v(qtype, text="Explain how database indexes speed up reads.", **kw):
    args = dict(difficulty="medium", expected_concepts=None, rubric=None, options=None, correct_option_index=None, test_cases=None)
    args.update(kw)
    return validate_structure(qtype, text, **args)


def test_mcq_needs_three_distinct_options_and_valid_key():
    assert not v(QuestionType.MCQ, options=["A", "B"], correct_option_index=0).ok
    assert not v(QuestionType.MCQ, options=["A", "a", "B"], correct_option_index=0).checks["mcq_distinct"]
    assert not v(QuestionType.MCQ, options=["A", "B", "C"], correct_option_index=3).checks["mcq_answer_key"]
    assert v(QuestionType.MCQ, options=["A", "B", "C"], correct_option_index=1).ok


def test_mcq_all_of_the_above_is_ambiguous():
    r = v(QuestionType.MCQ, options=["x", "y", "All of the above"], correct_option_index=2)
    assert not r.checks["mcq_unambiguous"]


def test_technical_requires_concepts_and_rubric():
    r = v(QuestionType.TECHNICAL)
    assert not r.ok and not r.checks["expected_concepts"] and not r.checks["rubric"]
    assert v(QuestionType.TECHNICAL, expected_concepts=["btree", "selectivity"], rubric={"criteria": ["x"]}).ok


def test_coding_requires_shaped_test_cases():
    assert not v(QuestionType.CODING, test_cases=[{"input": "1", "expected_output": "2"}]).ok
    assert not v(QuestionType.CODING, test_cases=[{"in": 1}, {"in": 2}]).checks["test_case_shape"]
    assert v(QuestionType.CODING, test_cases=[{"input": "1", "expected_output": "2"}, {"input": "2", "expected_output": "3"}]).ok


def test_bad_difficulty_and_truncation_rejected():
    assert not v(QuestionType.TECHNICAL, difficulty="impossible", expected_concepts=["a", "b"], rubric={"criteria": ["c"]}).ok
    assert not v(QuestionType.TECHNICAL, text="Explain indexes and...", expected_concepts=["a", "b"], rubric={"criteria": ["c"]}).checks["answerability"]


def test_content_hash_ignores_case_and_whitespace():
    assert content_hash("What  is Docker?") == content_hash("what is docker?")
