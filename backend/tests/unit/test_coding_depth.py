"""Visible/hidden test model and two-source verification with pruning."""
import pytest

from app.services.coding import judge0_client as jc
from app.services.coding import test_model as tm
from app.services.questions import coding_verification as cv
from app.services.questions.validator import validate_structure
from app.models.enums import QuestionType

CATS = ["normal", "normal", "boundary_minimum", "empty", "single_element", "maximum_size", "duplicates", "negative_values",
        "ordering", "special_case", "performance", "all_equal"]


def _tests(n=12, visible=2):
    return [{"input": f"[{i}]", "expected_output": str(i), "visible": i < visible, "category": CATS[i % len(CATS)]} for i in range(n)]


def test_samples_expose_only_visible_tests_and_legacy_rule():
    t = _tests(12, 3)
    assert [s["input"] for s in tm.sample_view(t)] == ["[0]", "[1]", "[2]"] and tm.hidden_count(t) == 9
    legacy = [{"input": "a", "expected_output": "1"}, {"input": "b", "expected_output": "2"}, {"input": "c", "expected_output": "3"}]
    assert len(tm.sample_view(legacy)) == 2 and tm.hidden_count(legacy) == 1
    assert all(x["input"] != "c" for x in tm.sample_view(legacy))
    assert [s["input"] for s in tm.sample_view([{"input": "x", "expected_output": "y", "visible": False}])] == []  # all hidden


def test_normalize_dedupes_caps_samples_and_promotes():
    t = _tests(10, 5) + [{"input": "[0]", "expected_output": "0", "visible": False, "category": "normal"}]
    n = tm.normalize(t)
    assert len(n) == 10 and sum(x["visible"] for x in n) == 3  # duplicate input removed, samples capped at 3
    none_visible = tm.normalize(_tests(10, 0))
    assert sum(x["visible"] for x in none_visible) == 2  # promoted


def test_depth_rules():
    assert tm.depth_problems(tm.normalize(_tests(12))) == []
    assert any("verified tests" in p for p in tm.depth_problems(tm.normalize(_tests(5))))
    same_cat = [{**x, "category": "normal"} for x in _tests(12)]
    assert any("categories" in p for p in tm.depth_problems(tm.normalize(same_cat)))


def test_validator_is_strict_for_generated_but_not_imported():
    args = (QuestionType.CODING, "Write a program that reads a list and prints the LIS length.", "medium", None, None, None, None)
    assert validate_structure(*args, _tests(3)).ok
    assert not validate_structure(*args, _tests(3), strict_tests=True).ok
    assert validate_structure(*args, _tests(12), strict_tests=True).ok


class _GW:
    async def generate_structured(self, prompt, schema, **kw):
        return schema(solution="print(1)")


def _patch(monkeypatch, agree):
    monkeypatch.setattr(cv, "get_ai_gateway", lambda: _GW())

    async def run_many(self, src, lang, tests):
        return [{"status": {"id": 3 if agree(i) else 4, "description": "x"}} for i in range(len(tests))]
    monkeypatch.setattr(jc.Judge0Client, "run_many", run_many)


@pytest.mark.asyncio
async def test_disagreeing_tests_are_pruned_not_trusted(monkeypatch):
    _patch(monkeypatch, lambda i: i not in (4, 9))  # two of 14 disagree
    ok, why, kept = await cv.verify_and_prune("p", _tests(14))
    assert ok and len(kept) == 12 and "[4]" not in [k["input"] for k in kept] and "2 disagreeing" in why
    assert sum(k["visible"] for k in kept) in (2, 3)


@pytest.mark.asyncio
async def test_too_many_disagreements_reject_the_question(monkeypatch):
    _patch(monkeypatch, lambda i: i < 8)  # 6 of 14 disagree (>40%): the reference or the author is unreliable
    ok, why, _ = await cv.verify_and_prune("p", _tests(14))
    assert not ok and "disagreed" in why
    _patch(monkeypatch, lambda i: i < 6)  # only 6 verified
    ok, why, _ = await cv.verify_and_prune("p", _tests(10))
    assert not ok


@pytest.mark.asyncio
async def test_runner_down_fails_closed(monkeypatch):
    monkeypatch.setattr(cv, "get_ai_gateway", lambda: _GW())

    async def down(self, *a, **k):
        raise jc.ExecutionUnavailable("down")
    monkeypatch.setattr(jc.Judge0Client, "run_many", down)
    ok, why, kept = await cv.verify_and_prune("p", _tests(12))
    assert not ok and "unavailable" in why and kept == []
