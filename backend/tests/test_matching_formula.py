from app.services.matching.engine import skill_fit


def test_skill_fit_caps_at_one():
    assert skill_fit(student_level=1.0, required_level=0.5) == 1.0


def test_skill_fit_proportional_below_required():
    assert skill_fit(student_level=0.4, required_level=0.8) == 0.5


def test_skill_fit_zero_required_level_is_full_credit():
    assert skill_fit(student_level=0.0, required_level=0.0) == 1.0


def test_skill_fit_zero_evidence():
    assert skill_fit(student_level=0.0, required_level=0.6) == 0.0
