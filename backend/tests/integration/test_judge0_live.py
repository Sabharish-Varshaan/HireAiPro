"""Runs HireAiPro's real Judge0 client against the cgroup-v2 Judge0 stack
(docker compose --profile judge0). Every case must be judged by Judge0 itself;
none may reach the local fallback."""
import pytest

from app.services.coding.judge0_client import Judge0Client

pytestmark = [pytest.mark.judge0, pytest.mark.asyncio]

CASES = [
    ("accepted", "import ast,sys\nprint(sum(ast.literal_eval(sys.stdin.read())))", "[1,2,3]", "6", {"Accepted"}),
    ("wrong", "print(5)", "", "6", {"Wrong Answer"}),
    ("runtime error", "raise SystemExit(3)", "", None, {"Runtime Error (NZEC)"}),
    ("cpu loop", "while True: pass", "", None, {"Time Limit Exceeded"}),
    ("sleep past wall", "import time; time.sleep(60)", "", None, {"Time Limit Exceeded"}),
    ("memory bomb", "x = bytearray(1024**3); print('ALLOCATED')", "", None, {"Runtime Error (NZEC)", "Runtime Error (SIGKILL)", "Memory Limit Exceeded"}),
]


@pytest.mark.parametrize("name,src,stdin,expected,statuses", CASES, ids=[c[0] for c in CASES])
async def test_verdicts(name, src, stdin, expected, statuses):
    r = await Judge0Client().run(src, "python", stdin=stdin, expected_output=expected)
    assert r["execution_backend"] == "judge0", r
    assert r["status"]["description"] in statuses, r
    assert "ALLOCATED" not in (r.get("stdout") or "")


async def test_sandbox_blocks_network_and_host_access():
    src = """import os, socket
bad = []
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2); bad.append("net")
except OSError: pass
for p in ("/usr/pwn", "/api/pwn"):
    try: open(p, "w").write("x"); bad.append(p)
    except OSError: pass
if os.getuid() == 0: bad.append("root")
bad += [k for k in os.environ if "PASS" in k or "REDIS" in k or "POSTGRES" in k]
print("clean" if not bad else bad)"""
    r = await Judge0Client().run(src, "python", expected_output="clean")
    assert r["execution_backend"] == "judge0" and r["status"]["description"] == "Accepted", r


async def test_fork_bomb_is_capped():
    src = """import os
n = 0
try:
    while n < 1000:
        if os.fork() == 0:
            import time; time.sleep(3); os._exit(0)
        n += 1
except OSError: pass
print("capped" if n < 1000 else "UNLIMITED")"""
    r = await Judge0Client().run(src, "python", expected_output="capped")
    assert r["execution_backend"] == "judge0" and r["status"]["description"] == "Accepted", r
