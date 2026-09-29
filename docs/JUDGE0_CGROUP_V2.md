# Judge0 on cgroup v2 (Docker Desktop, Apple Silicon)

Status: **adopted** (2026-09-29). Judge0 now sandboxes code on this M4 Mac. The local fallback is
unchanged and is used only when Judge0 is not running.

## Languages
Python 3.8.1, Node.js 22.23.3 and C++17 (GCC 12.2) — details, pins and the 38-case matrix in
[JUDGE0_LANGUAGES.md](JUDGE0_LANGUAGES.md). The app now fails closed (503) when Judge0 is down.

## What was built
| Component | Source | Pin / verification |
|---|---|---|
| Judge0 app | judge0/judge0#599 (community PR, **unmerged**) | commit `6cf7851c7b161d6dae0213e26e79d6fdcce7453d`, checked in the build |
| Sandbox | ioi/isolate **v2.6** (official tag) | commit `19ec4bd3fac386ae4cb95a7d43d8188710154661`, checked in the build |
| Python 3.8.1 | python.org | GPG signature verified (Łukasz Langa, `E3FF2839…10250568`); sha256 pinned |
| Ruby 2.7.8 / OpenSSL 1.1.1w | ruby-lang.org / openssl GitHub release | sha256 pinned (two sources agree for Ruby) |
| Base | `debian:bookworm-slim` (supported) | — |

`infra/judge0/Dockerfile` builds all of it natively (arm64 or amd64).

## Source review
**judge0#599** (+34/−4, 2 files against its merge base):
- The entrypoint delegates cgroup-v2 controllers (`init/` and `isolate/`). Every write ends in
  `|| true`, so a delegation failure would be silent. The tests below prove the limits are enforced.
- `isolate_job.rb` drops the removed `--cg-timing` flag, adds `-n 512` open files, and falls back to
  max-rss for memory. All reasonable.
- The script reorganises `/sys/fs/cgroup`. **It must run with `cgroup: private`**. With `cgroup: host`
  it would restructure the Docker VM's root cgroup. Compose enforces `private`, and a check confirmed
  the VM root was left untouched.

**judge0/compilers#29**, the companion PR, was not used as-is:
- It clones isolate *unpinned* (`master`).
- It rebuilds ~30 toolchains from source using x86_64-only binaries (hours under emulation, and
  more disk than was free).

The base here therefore keeps only the runtime HireAiPro grades (Python 3.8.1). It uses the same
isolate v2.x, pinned.

## Deviations and findings (all fixed or accepted)
1. `judge0.conf` from the Judge0 source is sourced with `allexport` and overrides the container env,
   including hosts and *empty passwords*. It is removed in the image, so config comes only from env.
2. The `scripts/workers` supervisor needs `ps`. Without it the supervisor respawned workers until the
   Docker VM hit a **global OOM**, which also killed Qdrant (data verified intact afterwards).
   Fixes: add `procps`, `COUNT=1` worker, and `mem_limit`/`pids_limit` on every Judge0 container.
3. **Upstream Judge0 1.13 bug:** `wait=true` polls the status through Rails' per-request query cache,
   so any run longer than ~2 s never returns. Measured: 0.5 s returned, 3 s never did. HireAiPro's
   client used `wait=true` and fell back to **unsandboxed local execution on timeout**. A slow or
   hostile submission would therefore have escaped the sandbox. The client now submits and polls by
   token, and fails closed.
4. The fallback used to trigger on *any* "Internal Error". It now triggers only on the legacy
   cgroup-v1 failure message or when Judge0 is unreachable.
5. The Ruby 2.7 / OpenSSL 1.1 API layer is EOL upstream, as in Judge0 1.13's own image. It serves
   the localhost-only API, not the sandbox boundary. It is accepted for local and demo use, but
   Judge0 needs replacing before internet exposure.
6. Transparent hugepages are enabled in the Docker VM (`isolate-check-environment` warns). This
   affects timing precision, not isolation.
7. `/api/languages` lists languages whose runtimes aren't installed (for example Python 2.7). The app
   only submits id 71.

## Test evidence
Each tier was run 3× or more on the final image; all runs passed.

| Tier | What | Result |
|---|---|---|
| 1 | `infra/judge0/tests/isolate_attack_battery.sh`, run inside the running workers container: CPU loop, wall sleep, 1 GB memory bomb (OOM-killed at exactly 128,000 KB), fork bomb (capped ~59), network egress, `/etc/shadow`, container-only paths, secret canaries in env and files, writes outside the box, non-root/setuid, host PID view, output-size cap (EFBIG), ptrace, mount, cross-box read, leftover processes | **20/20** ×3 |
| 2 | `infra/judge0/tests/judge0_api_battery.py`, the same attacks plus AC/WA/RE/SyntaxError/TLE and output flood through the Judge0 REST API, plus 8 concurrent submissions | **14/14** ×4 |
| 3 | `backend/tests/integration/test_judge0_live.py` (`pytest -m judge0`), HireAiPro's own client | **8/8** |
| 4 | App E2E via `/coding/submit` | buggy 1/2, correct 2/2, infinite loop TLE on both tests, all `execution_backend=judge0` |
| unit | `tests/unit/test_judge0_client.py`: polling, fail-closed timeout, fallback rules | 6/6 |

Rerun the batteries:
```bash
docker exec -i -u root -e PY=/usr/local/python-3.8.1/bin/python3 hireai_judge0_workers bash -s < infra/judge0/tests/isolate_attack_battery.sh
python3 infra/judge0/tests/judge0_api_battery.py
cd backend && .venv/bin/pytest -q -m judge0
```
(The isolate battery uses boxes 1 and 2. On a busy worker, run it while no submissions are queued.)
