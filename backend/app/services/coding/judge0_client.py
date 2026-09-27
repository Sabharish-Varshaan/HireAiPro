import asyncio
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

# Judge0 1.13.1's bundled `isolate` (1.8.x) only supports the cgroup v1
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
# never trigger it.
JUDGE0_SANDBOX_ERROR_MARKERS = ("Internal Error", "Failed to create control group")


class Judge0Client:
    def __init__(self) -> None:
        self.base_url = settings.JUDGE0_URL

    async def run(self, source_code: str, language: str, stdin: str = "", expected_output: str | None = None) -> dict:
        language_id = LANGUAGE_IDS.get(language, LANGUAGE_IDS["python"])
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/submissions",
                params={"base64_encoded": "false", "wait": "true"},
                json={
                    "source_code": source_code,
                    "language_id": language_id,
                    "stdin": stdin,
                    "expected_output": expected_output,
                },
            )
            resp.raise_for_status()
            result = resp.json()

        if language == "python" and result.get("status", {}).get("description") in JUDGE0_SANDBOX_ERROR_MARKERS:
            return await _run_local_python_fallback(source_code, stdin, expected_output)
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


async def _run_local_python_fallback(source_code: str, stdin: str, expected_output: str | None) -> dict:
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
        }

    return await asyncio.to_thread(_execute)


_client: Judge0Client | None = None


def get_judge0_client() -> Judge0Client:
    global _client
    if _client is None:
        _client = Judge0Client()
    return _client
