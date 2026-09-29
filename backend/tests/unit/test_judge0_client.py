"""Judge0 client: poll-by-token, fail-closed, and exactly when the unsandboxed
local fallback may run (only when Judge0 is unreachable)."""
import base64

import httpx
import pytest

from app.services.coding import judge0_client as jc

b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731


def _fake_judge0(monkeypatch, statuses, final_extra=None, connect_error=False):
    """statuses: list of status dicts returned by successive polls."""
    calls = {"post": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if connect_error:
            raise httpx.ConnectError("refused", request=request)
        if request.method == "POST":
            calls["post"] += 1
            assert request.url.params["wait"] == "false" and request.url.params["base64_encoded"] == "true"
            return httpx.Response(201, json={"token": "tok-1"})
        i = min(calls["get"], len(statuses) - 1)
        calls["get"] += 1
        body = {"token": "tok-1", "status": statuses[i], "stdout": None, "stderr": None, "time": "0.01", "memory": 3000}
        if i == len(statuses) - 1 and final_extra:
            body.update(final_extra)
        return httpx.Response(200, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(jc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(jc.asyncio, "sleep", _nosleep)
    return calls


async def _nosleep(_):
    return None


@pytest.mark.asyncio
async def test_polls_until_finished_and_decodes_output(monkeypatch):
    calls = _fake_judge0(monkeypatch, [{"id": 1}, {"id": 2}, {"id": 2}, {"id": 3, "description": "Accepted"}],
                         final_extra={"stdout": b64("6\n")})
    r = await jc.Judge0Client().run("print(6)", "python", expected_output="6")
    assert r["status"]["id"] == 3 and r["stdout"] == "6\n" and r["execution_backend"] == "judge0"
    assert calls["post"] == 1 and calls["get"] == 4


@pytest.mark.asyncio
async def test_long_run_is_not_cut_off_by_wait_mode(monkeypatch):
    # e.g. a TLE takes >2 s: many "Processing" polls, then the real verdict.
    _fake_judge0(monkeypatch, [{"id": 2}] * 10 + [{"id": 5, "description": "Time Limit Exceeded"}])
    r = await jc.Judge0Client().run("while True: pass", "python")
    assert r["status"]["description"] == "Time Limit Exceeded" and r["execution_backend"] == "judge0"


@pytest.mark.asyncio
async def test_poll_timeout_fails_closed_never_runs_locally(monkeypatch):
    _fake_judge0(monkeypatch, [{"id": 2}])
    monkeypatch.setattr(jc.settings, "JUDGE0_POLL_TIMEOUT_SECONDS", 0)
    ran_locally = []
    monkeypatch.setattr(jc, "_run_local_python_fallback", lambda *a, **k: ran_locally.append(a))
    r = await jc.Judge0Client().run("import time; time.sleep(999)", "python")
    assert not ran_locally
    assert r["status"]["id"] == 13 and r["execution_backend"] == "judge0"


@pytest.mark.asyncio
async def test_generic_internal_error_does_not_fall_back(monkeypatch):
    _fake_judge0(monkeypatch, [{"id": 13, "description": "Internal Error"}], final_extra={"message": b64("box died")})
    ran_locally = []
    monkeypatch.setattr(jc, "_run_local_python_fallback", lambda *a, **k: ran_locally.append(a))
    r = await jc.Judge0Client().run("print(1)", "python")
    assert not ran_locally and r["execution_backend"] == "judge0"


@pytest.mark.asyncio
async def test_legacy_cgroup_v1_failure_still_uses_dev_fallback(monkeypatch):
    _fake_judge0(monkeypatch, [{"id": 13, "description": "Internal Error"}],
                 final_extra={"message": b64("Failed to create control group /sys/fs/cgroup/memory/box-1/")})
    r = await jc.Judge0Client().run("print(1)", "python", expected_output="1")
    assert r["execution_backend"] == "local_fallback"


@pytest.mark.asyncio
async def test_unreachable_judge0_uses_dev_fallback_python_only(monkeypatch):
    _fake_judge0(monkeypatch, [], connect_error=True)
    r = await jc.Judge0Client().run("print(2)", "python", expected_output="2")
    assert r["execution_backend"] == "local_fallback" and r["status"]["id"] == 3
    with pytest.raises(httpx.ConnectError):
        await jc.Judge0Client().run("int main(){}", "cpp")
