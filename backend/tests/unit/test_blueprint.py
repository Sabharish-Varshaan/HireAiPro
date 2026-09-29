import uuid

from app.services.assessments.blueprint import build_blueprint


def _skill(name, importance, skill_id=None):
    return {"skill_id": skill_id or uuid.uuid4(), "skill_name": name, "importance": importance}


def test_empty_skills_returns_empty_blueprint():
    bp = build_blueprint([])
    assert bp.total_questions == 0
    assert bp.allocations == []


def test_higher_importance_gets_more_questions():
    skills = [_skill("Python", 1.0), _skill("HTML", 0.1)]
    bp = build_blueprint(skills, target_total_questions=12)
    by_name = {a.skill_name: a for a in bp.allocations}
    python_total = by_name["Python"].mcq_count + by_name["Python"].technical_count + by_name["Python"].coding_count
    html_total = by_name["HTML"].mcq_count + by_name["HTML"].technical_count + by_name["HTML"].coding_count
    assert python_total > html_total


def test_problem_solving_skills_route_to_coding_only():
    skills = [_skill("Data Structures", 0.8), _skill("Algorithms", 0.7)]
    bp = build_blueprint(skills)
    for alloc in bp.allocations:
        assert alloc.coding_count > 0
        assert alloc.mcq_count == 0
        assert alloc.technical_count == 0


def test_every_skill_gets_at_least_one_question():
    skills = [_skill("Python", 1.0), _skill("Rare Skill", 0.05)]
    bp = build_blueprint(skills, target_total_questions=12)
    for alloc in bp.allocations:
        assert (alloc.mcq_count + alloc.technical_count + alloc.coding_count) >= 1


def test_single_question_skills_get_mcqs_so_the_assessment_has_breadth():
    names = ["Python", "PostgreSQL", "SQL", "REST APIs", "FastAPI", "Git", "Docker", "Redis"]
    skills = [_skill(n, 1.0 - i * 0.08) for i, n in enumerate(names)] + [_skill("Algorithms", 0.75), _skill("Data Structures", 0.75)]
    bp = build_blueprint(skills, target_total_questions=10)
    mcq = sum(a.mcq_count for a in bp.allocations)
    tech = sum(a.technical_count for a in bp.allocations)
    assert mcq >= 3 and tech >= 3 and mcq + tech == 8  # ~40% of the 8 non-coding questions are MCQ
    by = {a.skill_name: a for a in bp.allocations}
    assert by["Python"].technical_count == 1 and by["Redis"].mcq_count == 1  # depth for the important, breadth for the rest
    assert all(a.mcq_count + a.technical_count + a.coding_count >= 1 for a in bp.allocations)
    assert bp.total_questions == 10


def test_breadth_rule_is_deterministic_and_skips_tiny_assessments():
    skills = [_skill("Python", 1.0), _skill("SQL", 0.9), _skill("Git", 0.8)]
    assert sum(a.mcq_count for a in build_blueprint(skills, 3).allocations) == 0  # 3 single questions: too few to split
    many = [_skill(f"S{i}", 0.5) for i in range(8)]
    a = [(x.skill_name, x.mcq_count) for x in build_blueprint(many, 8).allocations]
    assert a == [(x.skill_name, x.mcq_count) for x in build_blueprint(many, 8).allocations]
