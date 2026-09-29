import asyncio
import base64
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.services.coding.languages import LanguageUnavailable, judge0_id_for

settings = get_settings()


# Student code runs only inside Judge0 (infra/judge0: isolate v2 on cgroup v2).
# If Judge0 is down, times out, or lacks the language, run() raises
# ExecutionUnavailable -> HTTP 503 EXECUTION_SERVICE_UNAVAILABLE; nothing is
# scored. _run_local_python_fallback (Python only, NO isolation) remains solely
# as a developer opt-in: APP_ENV=development AND ALLOW_UNSANDBOXED_CODE_EXECUTION=true.
JUDGE0_SANDBOX_ERROR_MARKERS = ("Internal Error", "Failed to create control group")


def _is_legacy_cgroup_v1_failure(result: dict) -> bool:
    """The judge0/judge0:1.13.1 image on a cgroup-v2 host: "Internal Error" whose
    message is the cgroup creation failure. A generic Internal Error from a working
    sandbox must NOT trigger the unsandboxed fallback."""
    desc = (result.get("status") or {}).get("description") or ""
    message = result.get("message") or ""
    return desc == "Internal Error" and ("control group" in message or "cgroup" in message)


class ExecutionUnavailable(Exception):
    """EXECUTION_SERVICE_UNAVAILABLE: Judge0 cannot run the code right now; retryable.
    Nothing is scored and no evidence is written."""


class _PollTimeout(Exception):
    pass


def unsandboxed_execution_allowed() -> bool:
    """Both switches, and never outside development."""
    return settings.APP_ENV == "development" and settings.ALLOW_UNSANDBOXED_CODE_EXECUTION


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class Judge0Client:
    def __init__(self) -> None:
        self.base_url = settings.JUDGE0_URL

    async def run(self, source_code: str, language: str, stdin: str = "", expected_output: str | None = None) -> dict:
        """Sandboxed execution in Judge0, or ExecutionUnavailable. Never runs student
        code on the host unless unsandboxed_execution_allowed() (dev opt-in only)."""
        try:
            language_id = await judge0_id_for(language)
            result = await self._judge0(source_code, language_id, stdin, expected_output)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, LanguageUnavailable, _PollTimeout) as exc:
            return await self._unavailable(source_code, language, stdin, expected_output, f"{type(exc).__name__}: {exc}"[:200])
        if _is_legacy_cgroup_v1_failure(result):
            return await self._unavailable(source_code, language, stdin, expected_output, "Judge0 sandbox error (cgroup v1 image on cgroup v2 host)")
        result["execution_backend"] = "judge0"
        result["judge0_language_id"] = language_id
        return result

    async def _unavailable(self, source_code, language, stdin, expected_output, why: str) -> dict:
        if language == "python" and unsandboxed_execution_allowed():
            return await _run_local_python_fallback(source_code, stdin, expected_output, why)
        raise ExecutionUnavailable(why)

    async def _judge0(self, source_code, language_id, stdin, expected_output) -> dict:
        """Submit, then poll by token. Judge0 1.13's wait=true re-reads the status
        through the per-request query cache, so any run longer than its first 2 s
        poll never returns (measured 2026-09-29); polling by token is the mode
        Judge0 recommends and has no such limit."""
        body = {"source_code": _b64(source_code), "language_id": language_id, "stdin": _b64(stdin)}
        if expected_output is not None:
            body["expected_output"] = _b64(expected_output)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{self.base_url}/submissions", params={"base64_encoded": "true", "wait": "false"}, json=body)
            resp.raise_for_status()
            token = resp.json()["token"]
            deadline = time.monotonic() + settings.JUDGE0_POLL_TIMEOUT_SECONDS
            while True:
                r = await client.get(f"{self.base_url}/submissions/{token}", params={"base64_encoded": "true"})
                r.raise_for_status()
                result = r.json()
                if (result.get("status") or {}).get("id", 0) > 2:  # 1 In Queue, 2 Processing
                    break
                if time.monotonic() > deadline:
                    raise _PollTimeout(f"Judge0 did not finish submission {token} in {settings.JUDGE0_POLL_TIMEOUT_SECONDS}s")
                await asyncio.sleep(0.25)
        for field in ("stdout", "stderr", "compile_output", "message"):
            if result.get(field):
                result[field] = base64.b64decode(result[field]).decode("utf-8", errors="replace")
        return result

    async def run_many(self, source_code: str, language: str, test_cases: list[dict]) -> list[dict]:
        """Order-preserving; submissions overlap (bounded) so polling latency does not stack per test."""
        sem = asyncio.Semaphore(4)

        async def one(tc: dict) -> dict:
            async with sem:
                return await self.run(
                    source_code, language, stdin=str(tc.get("input", "")),
                    expected_output=str(tc.get("expected_output", "")) if tc.get("expected_output") is not None else None,
                )

        return list(await asyncio.gather(*(one(tc) for tc in test_cases)))


async def _run_local_python_fallback(source_code: str, stdin: str, expected_output: str | None, why: str) -> dict:
    def _execute() -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "script.py"
            script_path.write_text(source_code)
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    ["python3", str(script_path)],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
            except subprocess.TimeoutExpired:
                stdout, stderr, returncode = "", "Time Limit Exceeded (local fallback)", -1
            elapsed = time.monotonic() - started

        accepted = returncode == 0 and (expected_output is None or stdout.strip() == expected_output.strip())
        status_description = "Accepted" if accepted else ("Runtime Error" if returncode != 0 else "Wrong Answer")
        return {
            "stdout": stdout,
            "stderr": stderr,
            "compile_output": None,
            "time": str(elapsed),
            "memory": None,
            "token": "local-fallback",
            "status": {"id": 3 if accepted else 4, "description": f"{status_description} (local fallback — see docs/LOCAL_SETUP.md)"},
            "execution_backend": "local_fallback",
            "fallback_reason": why,
        }

    return await asyncio.to_thread(_execute)


_client: Judge0Client | None = None


def get_judge0_client() -> Judge0Client:
    global _client
    if _client is None:
        _client = Judge0Client()
    return _client
