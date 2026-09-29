"""Judge0 client: live language-id resolution, poll-by-token, fail-closed, and the
double opt-in for the unsandboxed developer fallback."""
import base64
import json

import httpx
import pytest

from app.services.coding import judge0_client as jc
from app.services.coding import languages as L

b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731

# Deliberately NOT upstream Judge0 ids: the client must use whatever /languages says.
LIVE_LANGS = [{"id": 7001, "name": "Python (3.8.1)"}, {"id": 7002, "name": "JavaScript (Node.js 22.23.3)"},
              {"id": 7003, "name": "C++17 (GCC 12.2.0)"}]


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(jc.settings, "APP_ENV", "development")
    monkeypatch.setattr(jc.settings, "ALLOW_UNSANDBOXED_CODE_EXECUTION", False)
    L._cache.update(at=0.0, ids={}, names={})
    yield
    L._cache.update(at=0.0, ids={}, names={})


def _fake_judge0(monkeypatch, statuses, final_extra=None, connect_error=False, langs=LIVE_LANGS):
    calls = {"post": [], "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if connect_error:
            raise httpx.ConnectError("refused", request=request)
        if request.url.path == "/languages":
            return httpx.Response(200, json=langs)
        if request.method == "POST":
            calls["post"].append(json.loads(request.content))
            assert request.url.params["wait"] == "false" and request.url.params["base64_encoded"] == "true"
            return httpx.Response(201, json={"token": "tok-1"})
        i = min(calls["get"], len(statuses) - 1)
        calls["get"] += 1
        body = {"token": "tok-1", "status": statuses[i], "stdout": None, "stderr": None, "time": "0.01", "memory": 3000}
        if i == len(statuses) - 1 and final_extra:
            body.update(final_extra)
        return httpx.Response(200, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    async def _nosleep(_):
        return None
    monkeypatch.setattr(jc.asyncio, "sleep", _nosleep)
    return calls


@pytest.fixture
def no_local(monkeypatch):
    ran = []

    async def boom(*a, **k):
        ran.append(a)
        raise AssertionError("student code must not run on the host")
    monkeypatch.setattr(jc, "_run_local_python_fallback", boom)
    return ran


@pytest.mark.asyncio
@pytest.mark.parametrize("lang,live_id", [("python", 7001), ("javascript", 7002), ("cpp", 7003)])
async def test_uses_language_id_resolved_from_judge0(monkeypatch, lang, live_id):
    calls = _fake_judge0(monkeypatch, [{"id": 3, "description": "Accepted"}], final_extra={"stdout": b64("6\n")})
    r = await jc.Judge0Client().run("src", lang, expected_output="6")
    assert calls["post"][0]["language_id"] == live_id
    assert r["judge0_language_id"] == live_id and r["execution_backend"] == "judge0" and r["stdout"] == "6\n"


@pytest.mark.asyncio
async def test_long_run_is_polled_until_the_real_verdict(monkeypatch):
    _fake_judge0(monkeypatch, [{"id": 2}] * 10 + [{"id": 5, "description": "Time Limit Exceeded"}])
    r = await jc.Judge0Client().run("while True: pass", "python")
    assert r["status"]["description"] == "Time Limit Exceeded"


@pytest.mark.asyncio
async def test_poll_timeout_is_unavailable_not_a_score(monkeypatch, no_local):
    _fake_judge0(monkeypatch, [{"id": 2}])
    monkeypatch.setattr(jc.settings, "JUDGE0_POLL_TIMEOUT_SECONDS", 0)
    with pytest.raises(jc.ExecutionUnavailable):
        await jc.Judge0Client().run("import time; time.sleep(999)", "python")
    assert not no_local


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["python", "javascript", "cpp"])
async def test_judge0_down_is_unavailable_by_default(monkeypatch, no_local, lang):
    _fake_judge0(monkeypatch, [], connect_error=True)
    with pytest.raises(jc.ExecutionUnavailable):
        await jc.Judge0Client().run("print(1)", lang)
    assert not no_local


@pytest.mark.asyncio
async def test_flag_alone_outside_development_does_not_enable_host_execution(monkeypatch, no_local):
    _fake_judge0(monkeypatch, [], connect_error=True)
    monkeypatch.setattr(jc.settings, "ALLOW_UNSANDBOXED_CODE_EXECUTION", True)
    for env in ("demo", "production", "staging"):
        monkeypatch.setattr(jc.settings, "APP_ENV", env)
        with pytest.raises(jc.ExecutionUnavailable):
            await jc.Judge0Client().run("print(1)", "python")
    assert not no_local


@pytest.mark.asyncio
async def test_development_and_flag_together_allow_labelled_python_fallback(monkeypatch):
    _fake_judge0(monkeypatch, [], connect_error=True)
    monkeypatch.setattr(jc.settings, "ALLOW_UNSANDBOXED_CODE_EXECUTION", True)
    r = await jc.Judge0Client().run("print(2)", "python", expected_output="2")
    assert r["execution_backend"] == "local_fallback" and r["status"]["id"] == 3
    with pytest.raises(jc.ExecutionUnavailable):  # never for JS/C++
        await jc.Judge0Client().run("console.log(2)", "javascript")


@pytest.mark.asyncio
async def test_language_missing_from_judge0_is_unavailable(monkeypatch, no_local):
    _fake_judge0(monkeypatch, [{"id": 3}], langs=[{"id": 1, "name": "Python (3.8.1)"}])
    with pytest.raises(jc.ExecutionUnavailable):
        await jc.Judge0Client().run("int main(){}", "cpp")


@pytest.mark.asyncio
async def test_generic_internal_error_is_reported_not_rerun(monkeypatch, no_local):
    _fake_judge0(monkeypatch, [{"id": 13, "description": "Internal Error"}], final_extra={"message": b64("box died")})
    r = await jc.Judge0Client().run("print(1)", "python")
    assert r["execution_backend"] == "judge0" and r["status"]["id"] == 13 and not no_local


@pytest.mark.asyncio
async def test_legacy_cgroup_v1_failure_is_unavailable_by_default(monkeypatch, no_local):
    _fake_judge0(monkeypatch, [{"id": 13, "description": "Internal Error"}],
                 final_extra={"message": b64("Failed to create control group /sys/fs/cgroup/memory/box-1/")})
    with pytest.raises(jc.ExecutionUnavailable):
        await jc.Judge0Client().run("print(1)", "python")
