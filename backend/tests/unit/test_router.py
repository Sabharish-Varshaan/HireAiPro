"""Router, cost governor and fallback behaviour (tests A–J). Provider
responses are simulated at AIGateway._call so no tokens are spent."""

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.database import AsyncSessionLocal
from app.models.misc import AIRun
from app.services.ai_gateway import budget as B, providers as P
from app.services.ai_gateway.gateway import AIGateway, AIGatewayError, Usage
from app.services.ai_gateway.pricing import estimate_cost_usd


class Out(BaseModel):
    value: str


def state(spend: float, total: float | None = None) -> B.BudgetState:
    s = get_settings()
    total = spend if total is None else total
    remaining = s.OPENAI_STARTING_BUDGET_USD - total
    if remaining <= s.OPENAI_RESERVE_USD:
        st, r = B.HARD, B.RESERVE_REACHED
    elif spend >= s.OPENAI_DAILY_HARD_LIMIT_USD:
        st, r = B.HARD, B.BUDGET_EXHAUSTED
    elif spend >= s.OPENAI_DAILY_SOFT_LIMIT_USD:
        st, r = B.SOFT, "OPENAI_DAILY_SOFT_LIMIT"
    else:
        st, r = B.NORMAL, None
    return B.BudgetState(spend, total, st, r, s.OPENAI_DAILY_SOFT_LIMIT_USD, s.OPENAI_DAILY_HARD_LIMIT_USD, remaining)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    """Force both cloud providers 'configured' with dummy keys; clear cool-downs."""
    s = get_settings()
    monkeypatch.setattr(s, "GROQ_API_KEY", "gsk_test_dummy_key_value_000000")
    monkeypatch.setattr(s, "OPENAI_API_KEY", "sk-test-dummy-key-value-0000000")
    monkeypatch.setattr(s, "LOCAL_ONLY", False)
    P._cooldown_until.clear()
    yield
    P._cooldown_until.clear()


def budget_at(monkeypatch, spend, total=None):
    async def fake():
        return state(spend, total)
    monkeypatch.setattr(B, "budget_state", fake)


def fake_calls(monkeypatch, behaviour: dict):
    """behaviour[provider_name] = str (JSON reply) | Exception | callable. Records call order."""
    calls: list[str] = []

    async def _call(self, pv, prompt, system, temperature, json_schema):
        calls.append(pv.name)
        b = behaviour[pv.name]
        if isinstance(b, BaseException):
            raise b
        if callable(b):
            return b(), Usage(100, 0, 20)
        return b, Usage(1000, 200, 100)

    monkeypatch.setattr(AIGateway, "_call", _call)
    return calls


# A — env audit
def test_a_config_reports_presence_without_exposing_values():
    s = Settings(_env_file=None, GROQ_API_KEY="gsk_x" * 5, OPENAI_API_KEY="")
    assert bool(s.GROQ_API_KEY) and not s.OPENAI_API_KEY
    assert "gsk_" not in repr(P.Provider("groq", "groq", "u", "m", "gsk_secret"))  # api_key excluded from repr


# B — Luna normal route
@pytest.mark.asyncio
async def test_b_jd_extraction_routes_to_luna(monkeypatch):
    budget_at(monkeypatch, 0.0)
    r = await P.route("jd_extraction")
    assert r.names == ["luna", "groq", "ollama"]
    assert r.chain[0].model == get_settings().OPENAI_CHEAP_MODEL


# C — agents route to Groq GPT-OSS-120B
@pytest.mark.asyncio
async def test_c_interview_agent_routes_to_groq(monkeypatch):
    budget_at(monkeypatch, 0.0)
    r = await P.route("agent:interview_agent")
    assert r.names[0] == "groq" and r.chain[0].model == "openai/gpt-oss-120b"
    assert "sol" not in r.names


# D — Groq 429: immediate fallback, no retry storm, reason recorded, cool-down set
@pytest.mark.asyncio
async def test_d_groq_429_falls_back_once(monkeypatch):
    budget_at(monkeypatch, 0.0)
    calls = fake_calls(monkeypatch, {"groq": P.ProviderHTTPError("groq", 429, "rate limited"),
                                     "luna": '{"value": "ok"}', "ollama": '{"value": "local"}'})
    out = await AIGateway().generate_structured("x", Out, task_type="question_generation")
    assert out.value == "ok" and calls == ["groq", "luna"]
    async with AsyncSessionLocal() as db:
        ok = await db.scalar(select(AIRun).where(AIRun.task_type == "question_generation", AIRun.status == "COMPLETED")
                             .order_by(AIRun.created_at.desc()))
    assert ok.fallback_used and "groq" in ok.fallback_reason and "429" in ok.fallback_reason
    # the real client marks cool-down on 429; subsequent routing skips groq
    P.mark_rate_limited("groq", 30)
    r = await P.route("question_generation")
    assert "groq" not in r.names and "groq_rate_limited_cooldown" in r.notes


# E — Luna timeout: controlled fallback
@pytest.mark.asyncio
async def test_e_luna_timeout_falls_back(monkeypatch):
    budget_at(monkeypatch, 0.0)
    calls = fake_calls(monkeypatch, {"luna": httpx.ReadTimeout("slow"), "groq": '{"value": "groq"}', "ollama": '{"value": "l"}'})
    out = await AIGateway().generate_structured("x", Out, task_type="jd_extraction")
    assert out.value == "groq" and calls == ["luna", "groq"]


# F — soft cap prefers free path and disables Sol
@pytest.mark.asyncio
async def test_f_soft_cap_prefers_groq(monkeypatch):
    budget_at(monkeypatch, 0.25)
    r = await P.route("jd_extraction")
    assert r.names == ["groq", "luna", "ollama"] and "OPENAI_DAILY_SOFT_LIMIT" in r.notes
    r = await P.route("critical_complex_failure", escalate=True)
    assert "sol" not in r.names


# G — hard cap blocks all paid OpenAI; free/local still works
@pytest.mark.asyncio
async def test_g_hard_cap_blocks_openai(monkeypatch):
    budget_at(monkeypatch, 0.35)
    r = await P.route("jd_extraction")
    assert r.names == ["groq", "ollama"] and B.BUDGET_EXHAUSTED in r.notes
    calls = fake_calls(monkeypatch, {"groq": '{"value": "free"}', "luna": AssertionError("must not call"), "ollama": '{"value": "l"}'})
    assert (await AIGateway().generate_structured("x", Out, task_type="jd_extraction")).value == "free"
    assert calls == ["groq"]


@pytest.mark.asyncio
async def test_g2_reserve_blocks_openai_even_under_daily_cap(monkeypatch):
    budget_at(monkeypatch, 0.01, total=3.60)  # 6.50 - 3.60 = 2.90 <= 3.00 reserve
    r = await P.route("jd_extraction")
    assert "luna" not in r.names and B.RESERVE_REACHED in r.notes


# H — Sol never selected normally; only on explicit escalation under budget
@pytest.mark.asyncio
async def test_h_sol_only_on_explicit_escalation(monkeypatch):
    budget_at(monkeypatch, 0.0)
    for task in P.TASK_POLICY:
        assert "sol" not in (await P.route(task)).names, task
    assert "sol" not in (await P.route("jd_extraction", escalate=True)).names  # simple tasks never escalate
    assert (await P.route("critical_complex_failure", escalate=True)).names == ["groq", "luna", "sol", "ollama"]


# I — Groq down + OpenAI budget-blocked → Ollama
@pytest.mark.asyncio
async def test_i_local_fallback(monkeypatch):
    budget_at(monkeypatch, 0.40)
    calls = fake_calls(monkeypatch, {"groq": httpx.ConnectError("down"), "ollama": '{"value": "local"}',
                                     "luna": AssertionError("blocked")})
    out = await AIGateway().generate_structured("x", Out, task_type="agent:career_agent")
    assert out.value == "local" and calls == ["groq", "ollama"]


# J — our own bugs are never masked by switching providers
@pytest.mark.asyncio
async def test_j_programming_error_not_masked(monkeypatch):
    budget_at(monkeypatch, 0.0)
    calls = fake_calls(monkeypatch, {"luna": AttributeError("bug in our code"), "groq": '{"value": "x"}', "ollama": '{"value": "x"}'})
    with pytest.raises(AttributeError):
        await AIGateway().generate_structured("x", Out, task_type="jd_extraction")
    assert calls == ["luna"]
    calls = fake_calls(monkeypatch, {"luna": P.ProviderHTTPError("luna", 400, "bad request we built"),
                                     "groq": '{"value": "x"}', "ollama": '{"value": "x"}'})
    with pytest.raises(AIGatewayError):
        await AIGateway().generate_structured("x", Out, task_type="jd_extraction")
    assert calls == ["luna"]  # a 400 is our request's fault: fix it, don't hide it


@pytest.mark.asyncio
async def test_schema_invalid_retries_once_then_next_tier(monkeypatch):
    budget_at(monkeypatch, 0.0)
    calls = fake_calls(monkeypatch, {"luna": "not json", "groq": '{"value": "g"}', "ollama": '{"value": "l"}'})
    out = await AIGateway().generate_structured("x", Out, task_type="jd_extraction")
    assert out.value == "g" and calls == ["luna", "luna", "groq"]  # exactly one paid repair retry


@pytest.mark.asyncio
async def test_local_only_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "LOCAL_ONLY", True)
    assert (await P.route("agent:assessment_agent")).names == ["ollama"]


@pytest.mark.asyncio
async def test_cost_is_recorded_and_summed_for_openai_only(monkeypatch):
    budget_at(monkeypatch, 0.0)
    before = await B.get_openai_spend_today()
    fake_calls(monkeypatch, {"luna": '{"value": "ok"}', "groq": '{"value": "g"}', "ollama": '{"value": "l"}'})
    await AIGateway().generate_structured("x", Out, task_type="rag_answer")
    after = await B.get_openai_spend_today()
    expected = estimate_cost_usd(get_settings().OPENAI_CHEAP_MODEL, 1000, 200, 100)
    assert after - before == pytest.approx(expected) and expected > 0
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(AIRun).where(AIRun.task_type == "rag_answer").order_by(AIRun.created_at.desc()))
    assert (row.provider, row.model, row.input_tokens, row.cached_input_tokens, row.output_tokens) == (
        "openai", get_settings().OPENAI_CHEAP_MODEL, 1000, 200, 100)


def test_pricing_registry():
    # gpt-6-luna: 800 uncached * 0.10 + 200 cached * 0.01 + 100 out * 0.50, per 1M
    assert estimate_cost_usd("gpt-6-luna", 1000, 200, 100) == pytest.approx((800 * 0.10 + 200 * 0.01 + 100 * 0.50) / 1e6)
    assert estimate_cost_usd("openai/gpt-oss-120b", 10**6, 0, 10**6) == 0.0
