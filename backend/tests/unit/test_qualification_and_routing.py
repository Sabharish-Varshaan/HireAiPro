"""Pure rules: the threshold decision, score normalisation/weighting, settings validation, and demand-based agent plans."""
import math

import pytest

from app.agents import orchestrator as orch
from app.services.pipeline import qualification as Q
from app.services.pipeline import stages as S


def test_the_rule_is_greater_or_equal_and_never_decides_without_a_score():
    assert Q.decide(72.0, 60.0) == Q.QUALIFIED
    assert Q.decide(70.0, 70.0) == Q.QUALIFIED  # exactly at the threshold qualifies
    assert Q.decide(69.9, 70.0) == Q.NOT_QUALIFIED
    assert Q.decide(None, 70.0) == Q.PENDING


def test_normalisation_is_centralised_on_a_0_100_scale():
    assert Q.pct(0.092) == 9.2 and Q.pct(1) == 100.0 and Q.pct(1.7) == 100.0 and Q.pct(-1) == 0.0


def test_weighted_round_score_uses_the_company_weights_and_refuses_to_guess():
    s = Q.combine({"mcq": 50.0, "written": 80.0, "coding": 100.0}, {"mcq": 20, "written": 20, "coding": 60})
    assert s.score == pytest.approx(86.0)
    assert Q.combine({"mcq": 50.0, "written": None}, {"mcq": 50, "written": 50}).score is None  # a weighted component is missing: no misleading number
    assert Q.combine({"mcq": 50.0, "written": None}, {"mcq": 50, "written": 50}).decision_hint == Q.MANUAL_REVIEW
    assert Q.combine({"mcq": 40.0, "written": 60.0}, None).score == 50.0  # unweighted: plain mean of what exists


def test_settings_validation():
    ok = Q.validate_settings(S.TECHNICAL, 70, True, {"mcq": 40, "written": 60})
    assert ok == (70.0, {"mcq": 40.0, "written": 60.0})
    assert Q.validate_settings(S.TECHNICAL, 0, True, None)[0] == 0.0 and Q.validate_settings(S.TECHNICAL, 100, True, None)[0] == 100.0
    for bad in (-1, 100.1, "abc", math.nan, math.inf):
        with pytest.raises(Q.SettingsError):
            Q.validate_settings(S.TECHNICAL, bad, False, None)
    with pytest.raises(Q.SettingsError):  # auto-qualification needs a number
        Q.validate_settings(S.TECHNICAL, None, True, None)
    with pytest.raises(Q.SettingsError):  # HR has no score
        Q.validate_settings(S.HR_INTERVIEW, 50, False, None)
    with pytest.raises(Q.SettingsError):  # weights must add up
        Q.validate_settings(S.TECHNICAL, 70, True, {"mcq": 40, "written": 40})
    with pytest.raises(Q.SettingsError):  # unknown component for the round
        Q.validate_settings(S.TECHNICAL, 70, True, {"coding": 100})
    with pytest.raises(Q.SettingsError):  # a single-result round has no components
        Q.validate_settings(S.APTITUDE, 70, True, {"mcq": 100})


def test_student_view_shows_score_and_requirement_but_never_reasoning():
    class St: pass_threshold, auto_qualify = 70.0, True
    class Rr:
        score, threshold, decision, reason, override_decision = 74.0, 70.0, Q.QUALIFIED, "at_or_above_threshold", None
        score_components, evaluated_at, evaluation_version = {"components": {}}, None, 1
    v = Q.view(St, Rr, "Technical Interview", audience="student")
    assert v == {"score": 74.0, "threshold": 70.0, "decision": Q.QUALIFIED, "result_label": "Qualified for the next round", "next": "Technical Interview"}
    Rr.score, Rr.decision = 64.0, Q.NOT_QUALIFIED
    v = Q.view(St, Rr, "Technical Interview", audience="student")
    assert v["result_label"] == "Round completed" and v["next"] is None and "reason" not in v and "components" not in v


# ------------------------------------------------------------------ demand-based routing (no provider is called)
def test_mcq_is_deterministic_and_calls_no_model():
    p = orch.plan_task("score_assessment", question_types={"MCQ"})
    assert p.agents == ["mcq_checker"] and not p.uses_llm and "assessment_evaluator" in p.skipped and "coding_evaluator" in p.skipped


def test_written_needs_the_rubric_evaluator_only_when_there_are_written_answers():
    assert orch.plan_task("score_assessment", question_types={"MCQ", "TECHNICAL"}).agents == ["mcq_checker", "assessment_evaluator"]
    assert orch.plan_task("score_assessment", question_types={"MCQ", "TECHNICAL"}, has_written_answers=False).agents == ["mcq_checker"]


def test_coding_selects_the_code_evaluator_and_nothing_else():
    p = orch.plan_task("score_coding")
    assert p.agents == ["coding_evaluator"] and not p.uses_llm
    assert not {"resume_evidence_agent", "audio_transcriber", "assessment_evaluator", "interview_agent"} & set(p.agents)


def test_resume_screening_uses_evidence_and_matching_but_not_audio_or_code():
    p = orch.plan_task("screen_resume")
    assert set(p.agents) == {"resume_evidence_agent", "matching_engine"}
    assert not {"audio_transcriber", "coding_evaluator"} & set(p.agents)


def test_interview_plans_follow_the_actual_demand():
    text = orch.plan_task("evaluate_interview_answer", stage_type="TECHNICAL_INTERVIEW", audio=False)
    voice = orch.plan_task("evaluate_interview_answer", stage_type="TECHNICAL_INTERVIEW", audio=True)
    hr = orch.plan_task("evaluate_interview_answer", stage_type="HR_INTERVIEW")
    assert text.agents == ["interview_evaluator"] and voice.agents == ["audio_transcriber", "interview_evaluator"] and hr.agents == ["hr_observer"]
    assert orch.plan_task("interview_next_question", stage_type="TECHNICAL_INTERVIEW", pool_ready=True).agents == ["depth_planner"]  # prepared pool: no model
    assert orch.plan_task("interview_next_question", stage_type="TECHNICAL_INTERVIEW", pool_ready=False).agents == ["interview_agent"]  # controlled fallback
    assert orch.plan_task("interview_next_question", stage_type="HR_INTERVIEW").agents == ["hr_selector"]


def test_the_qualification_step_is_deterministic_and_generation_is_the_only_generator():
    q = orch.plan_task("qualify_round")
    assert q.agents == ["qualification_engine"] and not q.uses_llm
    g = orch.plan_task("generate_questions")
    assert g.agents == ["assessment_agent"] and g.uses_llm and "interview_agent" in g.skipped


def test_plans_carry_hard_caps_and_unknown_tasks_are_refused():
    p = orch.plan_task("score_assessment", question_types={"MCQ", "TECHNICAL", "CODING"})
    assert p.max_steps == len(p.steps) <= 6 and p.max_llm_calls == 1 and p.timeout_seconds > 0
    with pytest.raises(orch.PlanError):
        orch.plan_task("decide_who_to_hire")  # there is no such task: no agent decides advancement


def test_every_llm_component_names_a_router_task_and_no_model():
    from app.services.ai_gateway.providers import TASK_POLICY

    for a in orch.REGISTRY.values():
        assert a.requires_llm == (a.router_task_type is not None), a.agent_id
        if a.router_task_type:
            assert a.router_task_type in TASK_POLICY, a.router_task_type  # the existing router owns model choice, fallback and timeouts
    assert not any(a.cost_class != "none" for a in orch.REGISTRY.values() if not a.requires_llm and not a.requires_code_execution and not a.requires_audio)
