"""Pure logic of the hiring pipeline: stage ordering, allocation, the technical-interview depth planner, HR safety and rotation."""
import pytest

from app.services.interviews import depth
from app.services.interviews.hr import HRObservation, pick_hr_question, sanitize
from app.services.interviews.hr_bank import PLATFORM_HR, logistics_questions
from app.services.interviews.hr_safety import clean_observation, is_safe_question, sensitive_hits
from app.services.pipeline import stages as S
from app.services.pipeline.stage_content import (_AptQ, aptitude_slots, check_aptitude, coding_allocations, largest_remainder,
                                                 technical_allocations)


# ------------------------------------------------------------------ ordering
def test_assessments_must_precede_interviews_but_can_reorder_inside_a_group():
    S.validate_order([S.CODING, S.APTITUDE, S.TECHNICAL, S.HR_INTERVIEW, S.TECH_INTERVIEW])  # reordering inside each group is fine
    S.validate_order([S.HR_INTERVIEW])
    for bad in ([S.HR_INTERVIEW, S.TECHNICAL], [S.TECH_INTERVIEW, S.CODING, S.HR_INTERVIEW], [S.APTITUDE, S.APTITUDE], ["NOPE"]):
        with pytest.raises(S.PipelineError):
            S.validate_order(bad)


def test_labels_never_expose_the_identifiers():
    for t in S.ALL_STAGES:
        assert "_" not in S.label(t) and S.label(t) != t
    assert S.label(S.TECH_INTERVIEW) == "Technical Interview" and S.label(S.HR_INTERVIEW) == "HR Interview"


# ------------------------------------------------------------------ allocation
def test_largest_remainder_is_exact_and_deterministic():
    r = largest_remainder(10, {"a": 1, "b": 1, "c": 1})
    assert sum(r.values()) == 10 and sorted(r.values()) == [3, 3, 4] and r == largest_remainder(10, {"a": 1, "b": 1, "c": 1})
    assert largest_remainder(0, {"a": 1}) == {"a": 0}


def test_aptitude_slots_follow_category_and_difficulty_mix():
    slots = aptitude_slots(20, {"Quantitative Aptitude": 50, "Logical Reasoning": 30, "Verbal Ability": 20}, {"easy": 30, "medium": 50, "hard": 20})
    assert len(slots) == 20
    per_cat = {c: sum(1 for x, _ in slots if x == c) for c in {c for c, _ in slots}}
    assert per_cat == {"Quantitative Aptitude": 10, "Logical Reasoning": 6, "Verbal Ability": 4}
    assert sum(1 for _, d in slots if d == "hard") in (3, 4, 5)


def test_technical_allocation_has_no_coding_and_respects_mcq_share():
    skills = [{"skill_id": f"s{i}", "skill_name": n, "importance": w} for i, (n, w) in enumerate([("Python", 0.9), ("SQL", 0.6), ("Git", 0.3)])]
    allocs = technical_allocations(skills, 12, 50)
    assert sum(a.mcq_count + a.technical_count for a in allocs) == 12 and all(a.coding_count == 0 for a in allocs)
    assert abs(sum(a.mcq_count for a in allocs) - 6) <= 1
    assert allocs[0].skill_name == "Python" and allocs[0].mcq_count + allocs[0].technical_count > allocs[-1].mcq_count + allocs[-1].technical_count


def test_technical_allocation_with_more_skills_than_questions_keeps_the_most_important():
    skills = [{"skill_id": f"s{i}", "skill_name": f"S{i}", "importance": 1 - i / 10} for i in range(8)]
    allocs = technical_allocations(skills, 3, 0)
    assert len(allocs) == 3 and [a.skill_name for a in allocs] == ["S0", "S1", "S2"]


def test_coding_allocation_prefers_problem_solving_and_is_coding_only():
    skills = [{"skill_id": "a", "skill_name": "Git", "importance": 0.9}, {"skill_id": "b", "skill_name": "Data Structures", "importance": 0.4},
              {"skill_id": "c", "skill_name": "Python", "importance": 0.8}]
    allocs = coding_allocations(skills, 2)
    assert [a.skill_name for a in allocs] == ["Data Structures", "Python"] or {a.skill_name for a in allocs} == {"Data Structures", "Git"}
    assert all(a.mcq_count == 0 and a.technical_count == 0 and a.coding_count >= 1 for a in allocs) and sum(a.coding_count for a in allocs) == 2
    assert sum(a.coding_count for a in coding_allocations(skills, 5)) == 5  # wraps around


def test_aptitude_question_structure_checks():
    ok = _AptQ(question_text="A train covers 120 km in 2 hours. What is its average speed?", options=["50", "60", "70", "80"], correct_option_index=1)
    assert check_aptitude(ok) is None
    assert check_aptitude(ok.model_copy(update={"options": ["50", "50", "70", "80"]}))
    assert check_aptitude(ok.model_copy(update={"options": ["50", "60", "70"]}))
    assert check_aptitude(ok.model_copy(update={"correct_option_index": 4}))
    assert check_aptitude(ok.model_copy(update={"options": ["50", "60", "70", "none of the above"]}))


# ------------------------------------------------------------------ interview depth planner
def _comps(*specs):
    return [depth.Comp(skill_id=s, name=s.upper(), importance=i, required=r, share=sh, min_q=mn, max_q=mx) for s, i, r, sh, mn, mx in specs]


COMPS = _comps(("py", 0.9, True, 0.5, 2, 4), ("sql", 0.7, True, 0.3, 1, 3), ("api", 0.4, False, 0.2, 1, 2))


def test_question_budget_scales_with_the_configured_duration():
    assert [depth.question_budget(m) for m in (30, 45, 60)] == [6, 9, 10] and depth.question_budget(None, 8) == 8
    assert depth.question_budget(10) == 6 and depth.question_budget(300) == 10


def test_blueprint_is_importance_weighted_and_bounded():
    bp = depth.build_blueprint([{"skill_id": "a", "name": "A", "importance": 0.9, "required": True},
                                {"skill_id": "b", "name": "B", "importance": 0.3, "required": False}], 9)
    assert bp[0]["share_pct"] > bp[1]["share_pct"] and sum(b["share_pct"] for b in bp) in (99, 100, 101)
    assert all(1 <= b["min_questions"] <= b["max_questions"] <= depth.DEFAULT_MAX_ASKS for b in bp)
    many = depth.build_blueprint([{"skill_id": str(i), "name": f"C{i}", "importance": 0.5, "required": True} for i in range(20)], 10)
    assert len(many) == depth.MAX_COMPETENCIES


def test_first_question_opens_the_most_important_competency_at_the_core_layer():
    p = depth.plan_next(COMPS, [], 8)
    assert (p.skill_id, p.layer, p.mode) == ("py", 1, "start")


def test_strong_answer_goes_deeper_weak_goes_to_fundamentals_uncertain_clarifies():
    strong = depth.plan_next(COMPS, [depth.TurnState("py", 1, 0.9, 0.9)], 8)
    assert (strong.skill_id, strong.layer, strong.mode) == ("py", 2, "deeper")
    weak = depth.plan_next(COMPS, [depth.TurnState("py", 1, 0.9, 0.9), depth.TurnState("py", 2, 0.2, 0.9)], 8)
    assert (weak.skill_id, weak.layer, weak.mode) == ("py", 1, "diagnostic")
    unsure = depth.plan_next(COMPS, [depth.TurnState("py", 2, 0.6, 0.3)], 8)
    assert (unsure.skill_id, unsure.layer, unsure.mode) == ("py", 2, "clarify")
    again = depth.plan_next(COMPS, [depth.TurnState("py", 2, 0.6, 0.3, mode="clarify")], 8)
    assert again.mode != "clarify"  # one clarification only


def test_weak_after_a_diagnostic_step_moves_to_another_competency():
    turns = [depth.TurnState("py", 2, 0.2, 0.9), depth.TurnState("py", 1, 0.2, 0.9, mode="diagnostic")]
    p = depth.plan_next(COMPS, turns, 8)
    assert p.skill_id != "py"


def test_adequate_answers_deepen_only_until_the_scenario_layer():
    p = depth.plan_next(COMPS, [depth.TurnState("py", 1, 0.6, 0.9)], 8)
    assert (p.skill_id, p.layer) == ("py", 2)
    p = depth.plan_next(COMPS, [depth.TurnState("py", 1, 0.9, 0.9), depth.TurnState("py", 2, 0.6, 0.9), depth.TurnState("py", 3, 0.6, 0.9)], 8)
    assert p.skill_id != "py"  # adequate at layer 3: enough depth on this competency


def test_a_competency_never_exceeds_its_question_limit_and_the_budget_ends_the_interview():
    turns = [depth.TurnState("api", 1, 0.9, 0.9), depth.TurnState("api", 2, 0.9, 0.9)]  # api max_q = 2
    assert depth.plan_next(COMPS, turns, 8).skill_id != "api"
    assert depth.plan_next(COMPS, [depth.TurnState("py", 1, 0.9, 0.9)] * 8, 8) is None
    assert depth.plan_next([], [], 8) is None


def test_coverage_is_protected_when_there_is_no_slack():
    # 3 competencies, budget 4, python already took 2 -> the two uncovered ones must be opened next even after a strong answer
    turns = [depth.TurnState("py", 1, 0.9, 0.9), depth.TurnState("py", 2, 0.9, 0.9)]
    p = depth.plan_next(COMPS, turns, 4)
    assert p.skill_id in ("sql", "api") and p.mode == "coverage"


def test_full_simulated_interview_covers_every_competency_without_exceeding_limits():
    turns: list[depth.TurnState] = []
    scores = iter([0.9, 0.9, 0.5, 0.8, 0.2, 0.9, 0.7, 0.9, 0.4, 0.9])
    while (p := depth.plan_next(COMPS, turns, 9)) is not None:
        turns.append(depth.TurnState(p.skill_id, p.layer, next(scores, 0.6), 0.9, mode=p.mode))
    counts = {c.skill_id: sum(1 for t in turns if t.skill_id == c.skill_id) for c in COMPS}
    assert all(counts[c.skill_id] >= 1 for c in COMPS) and all(counts[c.skill_id] <= c.max_q for c in COMPS) and 6 <= len(turns) <= 9
    py = [t.layer for t in turns if t.skill_id == "py"]
    assert max(py) >= 3  # the important competency was actually drilled


def test_exhausted_competencies_are_skipped():
    p = depth.plan_next(COMPS, [], 8, exhausted={"py"})
    assert p.skill_id == "sql"


def test_choose_from_pool_prefers_the_layer_skips_seen_and_varies_kind():
    class R:
        def __init__(self, skill, layer, kind, text):
            self.skill_id, self.layer, self.kind, self.question_text = skill, layer, kind, text

    rows = [R("py", 3, "scenario", "Scenario A"), R("py", 3, "scenario", "Scenario B"), R("py", 4, "debugging", "Debug A"), R("sql", 3, "scenario", "Other skill")]
    assert depth.choose_from_pool(rows, "py", 3, set(), []).question_text == "Scenario A"
    assert depth.choose_from_pool(rows, "py", 3, {"scenario a"}, []).question_text == "Scenario B"
    assert depth.choose_from_pool(rows, "py", 3, {"scenario a", "scenario b"}, ["scenario"]).question_text == "Debug A"  # nearest layer left
    assert depth.choose_from_pool(rows, "py", 3, {"scenario a", "scenario b", "debug a"}, []) is None


def test_turn_score_reads_the_rubric_and_tolerates_missing_evaluations():
    assert depth.turn_score(None) == (None, None) and depth.turn_score({}) == (None, None)
    s, c = depth.turn_score({"concept_accuracy": 1, "reasoning": 1, "completeness": 1, "communication": 1, "evaluator_confidence": 0.7})
    assert s == pytest.approx(1.0) and c == 0.7


# ------------------------------------------------------------------ HR safety / selection
def test_every_curated_hr_question_passes_the_safety_filter():
    for cat, qs in PLATFORM_HR.items():
        assert cat in S.HR_CATEGORIES and len(qs) >= 4
        for q in qs:
            assert is_safe_question(q), q


def test_sensitive_topics_are_rejected():
    for q in ["Are you planning to have children soon?", "What is your religion?", "How old are you and are you married?",
              "Do you have any medical conditions or a disability?", "Which political party do you support?", "Where is your accent from?",
              "Tell me about your mental health history", "Do you have a criminal record?", "Which gender do you identify with?"]:
        assert not is_safe_question(q), q
    assert is_safe_question("Tell me about a time you resolved a disagreement with a teammate.")
    assert sensitive_hits("She is pregnant and religious") == ["pregnant", "religious"]


def test_logistics_questions_come_from_the_posting_and_are_safe():
    class J:
        work_mode, location_city, employment_type = "ONSITE", "Pune", "INTERNSHIP"
        internship_duration_value, internship_duration_unit = 3, "MONTHS"

    qs = logistics_questions(J())
    assert any("Pune" in q for q in qs) and any("3 months" in q for q in qs) and all(is_safe_question(q) for q in qs)


def test_hr_observation_sanitizer_drops_sensitive_and_never_carries_a_score():
    obs = HRObservation(summary="Gave a clear example of resolving a scheduling conflict.",
                        key_points=["Cited a specific project", "Mentioned being pregnant", "Prefers written updates"], gave_concrete_example=True)
    out = sanitize(obs)
    assert out["key_points"] == ["Cited a specific project", "Prefers written updates"] and out["type"] == "hr_observation"
    assert not any(k in out for k in ("score", "overall_score", "rating", "personality", "culture_fit", "honesty", "emotion"))
    assert sanitize(HRObservation(summary="Talked about their religion at length"))["summary"] == ""
    assert clean_observation(["ok point", "medical history"]) == ["ok point"]


def test_hr_selection_rotates_categories_and_never_repeats():
    class R:
        def __init__(self, cat, text, source="platform_hr"):
            self.category, self.question_text, self.source = cat, text, source

    rows = [R("communication", "C1"), R("communication", "C2"), R("motivation", "M1"), R("motivation", "M2", "question_bank"), R("collaboration", "B1")]
    cats = ["communication", "motivation", "collaboration"]
    asked, seen, order = [], set(), []
    while (q := pick_hr_question(rows, cats, asked, seen)) is not None:
        order.append(q.question_text)
        asked.append(q.category)
        seen.add(q.question_text.lower())
    assert order[:3] == ["C1", "M2", "B1"]  # one per category first, the company bank first inside a category
    assert sorted(order) == sorted(r.question_text for r in rows)
