"""Generated coding tests are accepted only if an independent reference solution,
executed in Judge0, reproduces every expected output."""
import pytest

from app.services.coding import judge0_client as jc
from app.services.questions import coding_verification as cv


class _GW:
    def __init__(self, solution):
        self.solution, self.prompts = solution, []

    async def generate_structured(self, prompt, schema, **kw):
        self.prompts.append(prompt)
        return schema(solution=self.solution)


def _patch(monkeypatch, outputs=None, down=False):
    gw = _GW("print(42)")
    monkeypatch.setattr(cv, "get_ai_gateway", lambda: gw)

    async def run_many(self, src, lang, tests):
        if down:
            raise jc.ExecutionUnavailable("down")
        assert lang == "python" and src == "print(42)"
        return [{"status": {"id": 3 if ok else 4, "description": "Accepted" if ok else "Wrong Answer"}} for ok in outputs]
    monkeypatch.setattr(jc.Judge0Client, "run_many", run_many)
    return gw


TESTS = [{"input": "[3,1,4,1,5,9,2,6,5]", "expected_output": "5"}, {"input": "[1,2]", "expected_output": "2"}]


@pytest.mark.asyncio
async def test_all_reproduced_is_verified(monkeypatch):
    gw = _patch(monkeypatch, [True, True])
    ok, why = await cv.verify_test_cases("LIS problem", TESTS)
    assert ok and "Judge0" in why
    assert "expected" not in gw.prompts[0].lower().split("problem:")[1]  # reference never sees the tests
    assert "[3,1,4" not in gw.prompts[0]


@pytest.mark.asyncio
async def test_wrong_expected_output_is_rejected(monkeypatch):
    _patch(monkeypatch, [False, True])
    ok, why = await cv.verify_test_cases("LIS problem", TESTS)
    assert not ok and "test 1: Wrong Answer" in why


@pytest.mark.asyncio
async def test_runner_unavailable_fails_closed(monkeypatch):
    _patch(monkeypatch, down=True)
    ok, why = await cv.verify_test_cases("LIS problem", TESTS)
    assert not ok and "unavailable" in why
