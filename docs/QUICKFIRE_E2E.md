# Quickfire E2E

A fast integrity check of the **running** system: are the dependencies healthy, do tenant boundaries hold, and does one candidate get through all five hiring rounds.

```bash
backend/.venv/bin/python scripts/quickfire_e2e.py
```
Runs from the repository root with the backend virtualenv (it reads `backend/.env`, so it sees the same configuration as the API and worker). Healthy runtime: **about one minute** (55 s measured, most of it model calls: requirement extraction, the interview pool, six interview answers).

## Prerequisites
Everything in the README health-check table is up: API (8020), Postgres, Valkey, the Celery worker, Qdrant, at least one model provider (a cloud key or Ollama), and, for the coding round, Judge0. Skills must be seeded (README step 6). The script does not start services.

## What it does (all through the product's API, in order)
1. Preflight: API, Valkey, Celery worker ping, Qdrant, configured providers, Ollama (optional), Judge0 (optional: runs one real `print(6*7)` through the sandbox).
2. Accounts: Placement Officer (creates the institution), department and cohort, student invitation → email found in the dev outbox → account claimed → login; an independent outsider student; two recruiters at two companies.
3. Company A: creates a job, the job description goes to the model, requirements are extracted and confirmed; five company-private questions are created with answers the script knows (2 technical MCQ, 2 aptitude MCQ, 1 coding problem with 8 tests) — one carries a `QF_PRIVATE_<run id>` marker.
4. Tenant isolation: Company B cannot list the marker question, gets 404 reading it directly, and cannot read Company A's job or pipeline.
5. Hiring process: five stages (small counts, thresholds set) are configured, prepared by the worker and published; the officer sees the opportunity, approves it for the cohort; the eligible student sees it and applies; the outsider cannot.
6. Proctoring API lifecycle with **simulated** device data (no real camera or microphone is involved).
7. Rounds as the student: Aptitude (all right, 100 ≥ 50 → qualified, Technical unlocks); Technical (one wrong, 50 < 100 → not qualified, Coding refused by the server with `STAGE_LOCKED`, an override without a reason is refused, an override with a reason advances the candidate and keeps score/threshold/automatic decision); Coding (Judge0 Run then Submit, all tests pass); Technical Interview (3 questions, layers recorded, every answer scored, no repeat); HR Interview (3 questions, neutral observations, no technical score).
8. Candidate review: the recruiter's record shows every round, the override and the HR notes; the student payload has no recruiter-only fields; the officer payload has no scores.

Nothing is mocked, no score is hard-coded, and nothing is written to the database directly. Answers are correct or wrong on purpose so real scoring is compared with what the script knows.

## Output and exit codes
A line per check, then a summary and `Overall: PASS | DEGRADED | FAIL`.
| Exit | Overall | Meaning |
|---|---|---|
| 0 | PASS | every check passed, including Judge0 and Ollama |
| 1 | FAIL | a required check failed, or a required dependency (API, Valkey, worker, Qdrant, a model provider) is down; the run stops at the first failure |
| 2 | DEGRADED | only optional dependencies are blocked: Judge0 (coding) and/or Ollama |
Required: API, Valkey, worker, Qdrant, a model provider, and every product step other than coding. Optional: Judge0 and Ollama.

## Judge0 blocked
If the sandbox cannot run the trivial program, **Judge0 and Coding are reported BLOCKED with the reason**; the coding round is *skipped through the product's own "skip optional round" path* so the rest continues; nothing is executed on the host. Exit code 2.
The commonest cause after many local runs is `Sandbox ID out of range` (Judge0's submission counter passed 999 — isolate allows box ids 0–999), which shows as `Internal Error … /box/script.py`. Fix: `scripts/judge0_reset_ids.sh` (clears Judge0's own execution log; app data untouched) and re-run.
Verified: with the Judge0 probe pointed at a dead port the script reported Judge0 and Coding BLOCKED, the two interviews still passed, and it exited 2.

## Intentionally not covered
Excel/CSV/JSON import preview, written-answer rubric scoring, the full-length interview (6–10 questions; quickfire uses 3), voice answers/Whisper, real camera and microphone proctoring, browser UI, other roles' edge cases, re-evaluation and threshold versioning, exact-threshold edge case. These are covered by the backend integration tests (`pytest`) — see `docs/SYSTEM_AUDIT.md`.

## Cleanup
Records are left in place, named with the run id (`QF_<timestamp>`), so runs never collide. There is no delete endpoint for these records and the script never deletes database rows. Remove them only by resetting local data (README "Full reset").

## Troubleshooting
| Symptom | Likely cause and check |
|---|---|
| `Worker: no Celery worker answered` | start the worker (README step 9). The script must read `backend/.env` (it does this itself) — a worker started with a different broker URL will not answer |
| `Job + question bank: requirement extraction failed` | no model provider reachable (`GROQ`/`OPENAI` keys, or Ollama running with the model) |
| `Pipeline setup … did not finish` | the worker is busy or a provider is rate-limited; watch `celery` logs; raise `QUICKFIRE_GEN_TIMEOUT` (seconds, default 240) |
| `Accounts: invitation email not found` | `APP_ENV` is not `development`/`demo` (the dev outbox is disabled) |
| `Eligibility: … approved` fails | the student's department/cohort text does not match the officer's structure (the script creates both) |
| Any `FAIL` right after code changes | restart the API and the worker (no auto-reload) |
Override the API address with `QUICKFIRE_API=http://host:port/api/v1`.
