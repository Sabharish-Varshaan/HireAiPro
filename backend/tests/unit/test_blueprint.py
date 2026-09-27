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
