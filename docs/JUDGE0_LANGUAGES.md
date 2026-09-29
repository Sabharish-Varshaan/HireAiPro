# Judge0 languages (sandboxed coding)

Exactly three runtimes are installed in the pinned cgroup-v2 image (`infra/judge0`), and
`GET /languages` on the running Judge0 lists exactly these three (no archived entries):

| Stable id (app) | Judge0 name (live) | Judge0 id* | Runtime | Source / pin |
|---|---|---|---|---|
| `python` | Python (3.8.1) | 71 | CPython 3.8.1 | python.org tarball, GPG-verified (Łukasz Langa `E3FF2839…10250568`), sha256 `75894117…` |
| `javascript` | JavaScript (Node.js 22.23.3) | 102 | Node.js 22.23.3 LTS | official binary; SHASUMS256 GPG-verified (signer `5BE8A3F6…B168D356`); sha256 arm64 `a44aeb94…`, x64 `df450af8…` |
| `cpp` | C++17 (GCC 12.2.0) | 105 | Debian bookworm `g++ 12.2.0-14+deb12u1`, `-std=c++17 -O2` | Debian official repository |

\*The app never hardcodes these ids: `app/services/coding/languages.py` resolves them from the live
`/languages` by name (cached 5 min) and stores `judge0_language_id` on every coding submission.
Seed data: `infra/judge0/languages_active.rb` (replaces Judge0's 40-language list so only installed
runtimes exist) and an empty `languages_archived.rb`.

Base: `debian:bookworm-slim`; Judge0 app judge0/judge0#599 @ `6cf7851c`; sandbox ioi/isolate v2.6 @ `19ec4bd3`.

**Image size:** 1.21 GB (Python only) → **1.38 GB** with Node.js + C++ (+170 MB; g++ was already present
for building). No emulation, no full 30-language toolchain.

## Limits (per test case)
CPU 2 s (+1 s extra), wall 5 s, memory 128 MB (cgroup), 60 processes/threads, 512 open files,
1 MB output file, no network. C++ compilation runs in its own isolate step with Judge0's compile
limits (15 s CPU, 20 s wall, 512 MB, 120 processes). Judge0 worker count: **1**.

## How students write code
Every test's input arrives on **stdin** (generated problems use one line of JSON, e.g. `[1,2,3]`),
the program prints the answer on stdout, and the output is compared after trimming whitespace.
The Monaco selector changes the editor mode, the starter template and the submitted `language`.
Templates only read stdin and print; they contain no solution. LLM-generated starter code is never
shown (it contained full solutions in QA). Hidden test inputs/outputs never reach the browser.

## Test evidence (2026-09-29)
`infra/judge0/tests/judge0_language_matrix.py`: **38/38** — per language: correct, wrong answer,
syntax/compile error, infinite loop (TLE ≈2.08 s), 1 GB memory abuse (killed), 90 MB fits / 180 MB
killed, network, secret reads (env, /api, /proc/1/environ, /etc/shadow), writes outside the box,
fork/spawn bomb, setuid/privilege escalation; plus 3 simultaneous (py/js/cpp) and 6 queued
submissions with one worker (all finished, no OOM). App endpoint: `pytest -m judge0` (3 languages
through `/coding/submit`, evidence from Judge0 pass counts). Browser: Python (2/3), JavaScript (3/3)
and C++17 submissions all executed by Judge0.

**Known metric caveat:** isolate v2 reports `cg-mem` from cgroup `memory.peak`, which kernel 6.10
cannot reset between the compile and run steps, so compiled languages *report* the compiler's peak
(~195 MB). Enforcement is unaffected (180 MB C++ allocation is killed); the value is stored for audit
only and never scored.
