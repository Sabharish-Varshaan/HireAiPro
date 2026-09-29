import asyncio
import base64
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from app.core.config import get_settings

settings = get_settings()

LANGUAGE_IDS = {
    "python": 71,
    "javascript": 63,
    "java": 62,
    "cpp": 54,
    "c": 50,
    "go": 60,
}

# The stock judge0/judge0:1.13.1 image's `isolate` (1.8.x) only supports the cgroup v1
# hierarchy. Docker Desktop on Apple Silicon (and any host that only mounts
# cgroup v2 unified) makes every submission fail with a sandbox-level
# "Internal Error" ("Failed to create control group ... No such file or
# directory") before the student's code ever runs — this is an execution
# environment problem, not a code-correctness one. When that specific
# failure mode is detected, we fall back to running Python directly in a
# subprocess with a wall-clock timeout so the grading pipeline still
# executes *real* code and produces a *real* pass/fail, rather than
# reporting every submission as failed. This fallback never runs for
# non-Python languages and is not a substitute for Judge0's proper sandbox
# isolation (no memory/network restriction) — it exists only so local dev
# on an incompatible host isn't blocked. Production/CI hosts, which
# typically run cgroup v1 or hybrid, should hit real Judge0 execution and
# never trigger it. The repo's own build (infra/judge0, docs/JUDGE0_CGROUP_V2.md)
# uses isolate v2 and sandboxes on cgroup v2, so this path is now only reached
# when Judge0 is not running at all.
JUDGE0_SANDBOX_ERROR_MARKERS = ("Internal Error", "Failed to create control group")


def _is_legacy_cgroup_v1_failure(result: dict) -> bool:
    """The judge0/judge0:1.13.1 image on a cgroup-v2 host: "Internal Error" whose
    message is the cgroup creation failure. A generic Internal Error from a working
    sandbox must NOT trigger the unsandboxed fallback."""
    desc = (result.get("status") or {}).get("description") or ""
    message = result.get("message") or ""
    return desc == "Internal Error" and ("control group" in message or "cgroup" in message)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class Judge0Client:
    def __init__(self) -> None:
        self.base_url = settings.JUDGE0_URL

    async def run(self, source_code: str, language: str, stdin: str = "", expected_output: str | None = None) -> dict:
        language_id = LANGUAGE_IDS.get(language, LANGUAGE_IDS["python"])
        try:
            result = await self._judge0(source_code, language_id, stdin, expected_output)
        except httpx.ConnectError as exc:
            # Only an unreachable Judge0 (not running locally) may use the dev fallback.
            # Anything that reached Judge0 fails closed: a slow or hostile submission
            # must never be re-run outside the sandbox.
            if language != "python":
                raise
            return await _run_local_python_fallback(source_code, stdin, expected_output, f"Judge0 unreachable ({type(exc).__name__})")
        if language == "python" and _is_legacy_cgroup_v1_failure(result):
            return await _run_local_python_fallback(source_code, stdin, expected_output, "Judge0 sandbox error (cgroup v2 host)")
        result["execution_backend"] = "judge0"
        return result

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
                try:
                    r = await client.get(f"{self.base_url}/submissions/{token}", params={"base64_encoded": "true"})
                    r.raise_for_status()
                    result = r.json()
                    if (result.get("status") or {}).get("id", 0) > 2:  # 1 In Queue, 2 Processing
                        break
                except httpx.HTTPError:
                    pass  # transient poll failure; the deadline below still bounds the wait
                if time.monotonic() > deadline:
                    return {"token": token, "status": {"id": 13, "description": "Judge0 did not finish in time"},
                            "stdout": None, "stderr": None, "compile_output": None, "time": None, "memory": None}
                await asyncio.sleep(0.5)
        for field in ("stdout", "stderr", "compile_output", "message"):
            if result.get(field):
                result[field] = base64.b64decode(result[field]).decode("utf-8", errors="replace")
        return result

    async def run_many(self, source_code: str, language: str, test_cases: list[dict]) -> list[dict]:
        results = []
        for tc in test_cases:
            result = await self.run(
                source_code,
                language,
                stdin=str(tc.get("input", "")),
                expected_output=str(tc.get("expected_output", "")) if tc.get("expected_output") is not None else None,
            )
            results.append(result)
        return results


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
