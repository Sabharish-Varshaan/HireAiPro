# System audit

Audit date **2026-09-30**. Branch `main`, HEAD at the start of the audit `dc32700` ("Round qualification: deterministic threshold engine …"); the audit adds documentation, `scripts/quickfire_e2e.py` and `scripts/judge0_reset_ids.sh` on top.
Working tree was clean at the start (no dirty or untracked files). Every claim below comes from the current code, the running system or a test run in this audit. Evidence
labels: **RUNTIME** (observed against the running stack), **TEST** (automated test run today), **CODE** (read in the source, not run), **NOT TESTED**.

## 1. Result matrix
| Area | Status | Evidence |
|---|---|---|
| Services up (API, Postgres, Valkey, worker, Qdrant, Judge0, Ollama, Vite) | PASS | RUNTIME: quickfire preflight, `docker ps`, listening sockets |
| Migrations | PASS | RUNTIME: dev DB and test DB both at head `ff25cda85069` |
| Three-role account lifecycle (signup, invitation claim, login) | PASS | RUNTIME quickfire; TEST `test_accounts.py` |
| Password reset via dev outbox | PASS | TEST `test_accounts.py`; RUNTIME (browser, earlier session, reset page and flow) |
| Job creation, requirement extraction, confirmation | PASS | RUNTIME quickfire (real model call) |
| Campus flow: distribute → officer approval → eligible student applies; outsider blocked | PASS | RUNTIME quickfire; TEST `test_opportunities.py` |
| Rich job posting (types, internship, compensation, deadline) | PASS | TEST `test_job_posting*.py`; quickfire creates a job with type/mode/openings/deadline only |
| Company-private question bank, tenant isolation | PASS | RUNTIME quickfire (list empty, direct read 404); TEST `test_company_question_import.py`, `test_tenant_isolation.py`, `test_hiring_pipeline.py` |
| Excel / CSV / JSON templates and import preview | PASS | TEST `test_company_question_import.py`, `test_pipeline_extras.py`; not exercised by quickfire |
| Five-stage per-job pipeline, ordering, disable, publish freeze | PASS | RUNTIME quickfire (all five stages configured, prepared, published); TEST `test_hiring_pipeline.py` |
| Qualification engine (≥ threshold, missing/pending, override, versioning) | PASS | RUNTIME quickfire (100≥50 qualified; 50<100 not qualified, next locked, override); TEST `test_round_qualification.py`, `test_qualification_and_routing.py` |
| Aptitude as its own stage | PASS | CODE+TEST: own `Assessment` row, version, timer, attempt, domain-separated questions (`test_hiring_pipeline.py`); RUNTIME quickfire round |
| Technical assessment (MCQ + written), separate from coding | PASS | TEST; RUNTIME quickfire (MCQ only; written scoring is a model call, covered by tests with a fake provider) |
| Coding: Run, Submit, samples, hidden tests, Judge0 | PASS (after repair, see §6) | RUNTIME quickfire; TEST `-m judge0` 11 passed; Python only exercised end to end (JS/C++ covered by `-m judge0` matrix tests) |
| Technical interview: multi-turn, layered, adaptive | PASS | RUNTIME quickfire (3 turns, layers recorded, all scored); TEST 6–10 turns, drilling, no repeats |
| HR interview: separate, safe, no score | PASS | RUNTIME quickfire; TEST safety filter + separation |
| Adaptive agent orchestration | PASS (scope below) | TEST `test_qualification_and_routing.py` + trace row check |
| Model routing | PASS | CODE+TEST `test_router.py`; RUNTIME: providers configured (names only) |
| Proctoring session lifecycle | PASS with **SIMULATED device data** | RUNTIME quickfire (API lifecycle with simulated report); browser sessions earlier used an injected fake camera/mic. **REAL DEVICE TESTED: none.** |
| Voice answers (Whisper) | NOT TESTED at runtime | TEST `test_speech.py` (stub); real transcription not run in this audit |
| Score visibility | PASS, with two documented findings | TEST `test_score_visibility.py`; RUNTIME quickfire (student/officer payload checks); see §11 |
| Frontend build / lint | PASS | build rc 0; lint rc 0 (0 errors, 10 warnings) |
| Frontend component tests | NOT PRESENT | no `test` script in `frontend/package.json` |
| Browser test in this audit | NOT TESTED | no browser pass was made in this audit; earlier sessions' browser checks are not counted here |
| Live-model tests (`-m live`) | NOT RUN | need a local model; skipped by design (4 tests) |

## 2. Repository, stack and services
`backend/` FastAPI app (`app/api/v1` routes → `app/services` → SQLAlchemy models), `backend/migrations` (Alembic, 15 revisions), `backend/tests` (unit, integration, security, agents),
`frontend/` React SPA, `infra/judge0` (Judge0 image build), `docker-compose.yml`, `docs/`, `scripts/`. Versions installed here: Python 3.12.13, FastAPI 0.141.1, Uvicorn 0.54,
SQLAlchemy 2.1.1, Alembic 1.20, Celery 5.6.3, Pydantic 2.13, pydantic-ai 2.51, faster-whisper 1.2.1, Node 22.20, React 19.2, Vite 8.3, TypeScript ~6.0, Monaco editor 4.7.
Embedding/reranker models are BAAI BGE-M3 and bge-reranker-v2-m3 (loaded in-process, released after 300 s idle); speech is faster-whisper (`small.en`).

| Service | Port | How it runs | Verified |
|---|---|---|---|
| Frontend (Vite dev) | 5173 (proxies `/api` → 8020) | `npm run dev` | RUNTIME |
| API (FastAPI/Uvicorn) | 8020 | `uvicorn app.main:app --port 8020` (no auto-reload) | RUNTIME |
| Postgres 16 | 5435 → container 5432 | compose `postgres` | RUNTIME |
| Valkey 8 | 6380 → 6379 | compose `valkey` | RUNTIME |
| Qdrant | 6333 (HTTP), 6334 (gRPC) | compose `qdrant` (1 GB cap) | RUNTIME |
| Judge0 (cgroup-v2 build) | 127.0.0.1:2358 | compose profile `judge0` (server + workers + own Postgres + own Redis) | RUNTIME |
| Ollama | 11434 (native, not compose) | `ollama serve`; model `qwen3.5:4b` pulled | RUNTIME |
| Celery worker | (no port) | `celery -A app.workers.celery_app worker --pool=solo -Q documents,assessments,matching,knowledge,reports,celery` | RUNTIME (ping) |
Other listeners on this Mac (a Python service on 8026, Redis on 6379) belong to other projects and are not used.

## 3. Environment variables (names only)
File: copy `.env.example` (repo root) to `backend/.env`. The settings class is `backend/app/core/config.py`. `Required` means the app will not run correctly without it.
| Variable | Required | Service | Purpose | Safe default |
|---|---|---|---|---|
| `DATABASE_URL` | yes | API, worker, tests | Postgres (asyncpg URL) | example value for local compose |
| `VALKEY_URL` | yes | API, worker | Celery broker/result | local compose |
| `QDRANT_URL`, `QDRANT_COLLECTION_PREFIX` | yes / no | API, worker | vectors; prefix isolates tests (`test_`) | local compose |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES` | secret yes | API | tokens | **no**: set your own secret |
| `APP_ENV` / `ENV` | no | API | `development`/`demo` enables the email outbox; production disables it | development |
| `FRONTEND_BASE_URL`, `EMAIL_OUTBOX_ENVS`, `INVITE_TTL_HOURS`, `RESET_TTL_MINUTES` | no | API | invitation/reset links and lifetimes | yes |
| `LLM_PROVIDER`, `LOCAL_ONLY`, `LLM_PRIMARY_PROVIDER`, `LLM_CHEAP_PROVIDER`, `LLM_LOCAL_FALLBACK_PROVIDER`, `LLM_THINK` | no | AI gateway | routing mode; `LOCAL_ONLY=true` forces Ollama only | yes |
| `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_MODEL` | key optional | AI gateway | primary agentic provider | key: none |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_CHEAP_MODEL`, `OPENAI_ESCALATION_MODEL` | key optional | AI gateway | cheap/escalation provider | key: none |
| `OPENAI_DAILY_SOFT_LIMIT_USD`, `OPENAI_DAILY_HARD_LIMIT_USD`, `OPENAI_STARTING_BUDGET_USD`, `OPENAI_RESERVE_USD` | no | AI gateway | spend governor | yes |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | yes if no cloud key | AI gateway | local/fallback model | localhost:11434 / qwen3.5:4b |
| `LLM_MAX_RETRIES`, `LLM_MAX_AGENT_TURNS`, `LLM_TIMEOUT_SECONDS`, `LLM_OLLAMA_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_CONTEXT_CHARS` | no | AI gateway | per-call caps | yes |
| `EMBEDDING_MODEL`, `RERANKER_MODEL`, `EMBEDDING_FP16`, `MODEL_IDLE_UNLOAD_SECONDS` | no | API, worker | local embedding/rerank, idle release | yes |
| `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `MAX_AUDIO_BYTES` | no | API | speech-to-text | yes |
| `INTERVIEW_MAX_TURNS`, `INTERVIEW_EVAL_BUDGET_SECONDS`, `INTERVIEW_EVAL_CATCHUP_SECONDS` | no | API | legacy default length; answer scoring wait budget | yes |
| `JUDGE0_URL`, `JUDGE0_POLL_TIMEOUT_SECONDS` | yes for coding | API | code execution service | localhost:2358 |
| `ALLOW_UNSANDBOXED_CODE_EXECUTION` | no | API | developer opt-in, needs `APP_ENV=development`; default `false` | false |
| `PROCTOR_ENFORCE`, `PROCTOR_FULLSCREEN_REQUIRED`, `PROCTOR_CAMERA_REQUIRED`, `PROCTOR_MICROPHONE_REQUIRED`, `PROCTOR_HEARTBEAT_SECONDS`, `PROCTOR_HEARTBEAT_LOST_AFTER_SECONDS`, `PROCTOR_DEDUPE_WINDOW_MS` | no | API | proctoring gate and timing | enforce = true |
| `ASSESSMENT_SLOT_GENERATION_ATTEMPTS`, `SCORING_VERSION`, `MATCHING_VERSION` | no | API/worker | generation retries, version labels | yes |
| `JUDGE0_DB_PASSWORD`, `JUDGE0_REDIS_PASSWORD` | no | compose | Judge0's own stores (local-only defaults) | yes |
Frontend: no `VITE_*` variables are used; the API address is fixed in `vite.config.ts` (`/api` → `http://localhost:8020`). Note: `EMBEDDING_FP16`, `WHISPER_COMPUTE_TYPE`, `WHISPER_DEVICE` are set in the working `backend/.env` but are missing from `.env.example` (they have safe defaults in code).

## 4. Database and migrations
15 Alembic revisions, head `ff25cda85069` (round qualification: `round_results`, threshold/weights columns). `alembic current` reports head on both `hireai` (dev) and `hireai_test`; no pending migration. Schema is created only by
migrations (not on startup). Seeds are separate commands (`python -m app.services.skills.seed`, `python -m app.services.career.seed_resources`); a fresh database needs both (the skill taxonomy is required for job
requirement mapping). Migrations were applied to both databases by running `alembic upgrade head`; no user data was edited during this audit.

## 5. Roles and account lifecycle
Active roles: Placement Officer, Company/Recruiter, Student (`platform admin` is internal, created by CLI). Deferred and not built: institution admin, faculty, department head, SSO. RUNTIME (quickfire): officer signup (creates the
institution), department and cohort creation, student invitation, email found in the dev outbox (`GET /api/v1/dev/email-outbox`), account claim (`POST /auth/invitations/accept`), login, an independent (non-enrolled)
student signup, two recruiter signups. TEST: forgot/reset password, single-use and expiring invitation tokens, resend, disable/enable (`test_accounts.py`). No default or shared passwords exist.

## 6. Judge0 (explicit health check)
| Check | Result |
|---|---|
| Containers | `hireai_judge0_server`, `_workers`, `_db`, `_redis` up |
| `GET /about` | version `1.13.1-cgv2-pr599` |
| Smallest execution (`print(6*7)`, Python) at the start of the audit | **FAIL** `Internal Error`, message `No such file or directory @ rb_sysopen - /box/script.py`. Reproduced before and after restarting the containers, and with my changes stashed |
| Cause (worker log) | `Sandbox ID out of range (allowed: 0-999)` then `chown: cannot access '/box'`. Judge0 names each sandbox after its submission id (`box_id = submission.id % 2147483647`, `isolate_job.rb:55`); isolate 2.6 allows only 0–999; the counter was at 1022 |
| One bounded repair | cleared Judge0's own execution log and reset its id counter: `TRUNCATE submissions RESTART IDENTITY` in the `judge0` database (script: `scripts/judge0_reset_ids.sh`). HireAiPro's results live in its own database and were not touched |
| After repair | `print(6*7)` → `42`, status Accepted; quickfire coding round PASS; `pytest -m judge0`: 11 passed |
| Recurrence | **will return after about 1000 more executions**. The permanent fix (larger `num_boxes` / periodic cleanup / id remapping in the client) is not implemented. The quickfire preflight detects it, reports coding BLOCKED, and never falls back to host execution |
The API fails closed (`503 EXECUTION_SERVICE_UNAVAILABLE`) when Judge0 is unreachable; the local unsandboxed runner needs `APP_ENV=development` **and** `ALLOW_UNSANDBOXED_CODE_EXECUTION=true`.

## 7. Job and campus flow
RUNTIME (quickfire): job created (type, work mode, openings, deadline, fresher), JD sent to the model and requirements extracted, requirements confirmed, distribution set to a partner institution, hiring process published
→ appears in the officer's pending queue, invisible to the student until approved, officer approves with department, cohort and graduation year, the eligible student sees it and applies, an outsider student does not see it
and is refused (403/404). TEST: posting validation (`posting.py`), internship and internship→full-time fields, compensation/LPA normalisation, deadline enforcement after closing (`APPLICATIONS_CLOSED`).

## 8. Company-private question bank
Ownership: `organization_id` + `visibility=COMPANY_PRIVATE`, provenance COMPANY_IMPORT / COMPANY_MANUAL / AI_GENERATED_COMPANY_PRIVATE; domains APTITUDE, TECHNICAL, CODING, TECHNICAL_INTERVIEW, HR_INTERVIEW. Isolation:
RUNTIME quickfire: Company B's search finds nothing, a direct read is 404, Company B cannot read the job or its pipeline. TEST: another company cannot list, search, attach or read a question; its stage generation, interview
pools and model prompts contain none of Company A's marker text (`test_company_private_aptitude_and_interview_content_is_tenant_isolated`); tampered templates from another company are refused (422, nothing imported);
RAG and vector search take a mandatory tenant scope (`test_rag_pipeline.py`, `test_tenant_isolation.py`). Templates: Excel (Instructions/Questions/Metadata sheets), CSV, JSON, per domain; preview with statuses
(Ready/Warning/Invalid/Duplicate/Needs skill mapping), skill mapping, duplicate detection inside the company only, coverage table, attach to an assessment (TEST). The quickfire creates questions through the manual API, not the spreadsheet import.

## 9. Hiring pipeline and qualification
Stage types (code: `services/pipeline/stages.py`): `APTITUDE_ASSESSMENT`, `TECHNICAL_ASSESSMENT`, `CODING_ASSESSMENT`, `TECHNICAL_INTERVIEW`, `HR_INTERVIEW`. Per job: `hiring_stages` (enabled, order, duration, count,
proctored, config, threshold, weights) and per application `application_stage_progress` (LOCKED/AVAILABLE/IN_PROGRESS/COMPLETED/SKIPPED). Assessments must precede interviews; reordering inside a group only; publishing validates
only enabled stages and freezes content. Each assessment stage has its own frozen version, timer and attempt (TEST). Locked stages are refused by the server with `409 STAGE_LOCKED` (RUNTIME quickfire).

**Qualification (code `services/pipeline/qualification.py`)**: round score on 0–100; `score >= threshold` → QUALIFIED else NOT_QUALIFIED; a missing weighted component → MANUAL_REVIEW; scoring still running or a
provider failed → EVALUATION_PENDING (no decision, not a failure). Weighted score = Σ(component × weight)/Σ(weights); interview default weights accuracy 40, reasoning 25, completeness 25, communication 10
(e.g. 80/70/70/90 → 76.0, asserted in a test). Threshold, weights, components and engine version are stored with every result (`round_results`); changing settings never rewrites history, `POST …/evaluate` adds an audited
new version; override (advance/hold) needs a reason and is audited, the automatic result is never edited. No threshold = the round only completes (previous behaviour). RUNTIME: Aptitude 100 vs 50 qualified and unlocked
the next round; Technical 50 vs 100 not qualified, coding locked, override recorded, coding unlocked.

## 10. Rounds in detail
* **Aptitude**: own assessment/version/timer; categories quantitative, logical, analytical, data interpretation, verbal; questions carry `domain=APTITUDE`, no skill, no skill evidence; aptitude and technical/coding questions cannot be mixed (409). Generated
  questions are re-solved independently and discarded on disagreement (TEST). Company/platform banks first.
* **Technical assessment**: MCQ + written from the job's skills, never coding; MCQ scored deterministically, written by the rubric evaluator (model) with job context.
* **Coding**: separate stage; visible samples + hidden tests; Run vs Submit; the recruiter's language choice narrows each frozen problem; score comes from Judge0 test results only.
* **Technical interview**: frozen blueprint (weights, question range, depth); pool of layered questions prepared before candidates arrive (core → how/why → scenario → edge case → trade-off); deterministic planner (strong → deeper,
  weak → diagnostic, uncertain → clarify, ≤ 4 per competency, coverage protected); length from duration (30/45/60 min → 6/9/10) unless a count is set; candidates cannot finish before the minimum (`409 INTERVIEW_TOO_SHORT`).
  TEST: 6–10 turns, drilling, no repeats, next question < 1.5 s from the pool. RUNTIME quickfire uses a reduced 3-question interview; production defaults are not exercised by it. Live generation is only the controlled fallback when no prepared question can serve.
* **HR interview**: separate template/pool/turns; curated + company + posting-derived questions filtered by `hr_safety` (protected/sensitive topics rejected); neutral observations only; no score, no skill evidence, no effect on the match.

## 11. Agents, routing, proctoring, visibility
**Orchestration (`app/agents/orchestrator.py`)**: registry of the real components; `plan_task(task, **facts)` returns only the agents needed, with caps; a compact trace goes to `agent_runs`. TEST-verified plans: MCQ →
`mcq_checker`, no model; written → `assessment_evaluator`; coding → `coding_evaluator`, no model; resume screening → `resume_evidence_agent` + `matching_engine`; interview next question → `depth_planner`/`hr_selector`
(no model), `interview_agent` only as fallback; interview answer → evaluator (+ `audio_transcriber` for voice); qualification → `qualification_engine`, no model. **Scope**: assessment scoring and interview/HR answer
evaluation execute through these plans; other paths (job extraction, question generation, matching) keep their existing direct implementations and are not routed through `plan_task`.

**Model routing** (`ai_gateway/providers.py`): `CHEAP = luna → groq → ollama`; `AGENT = groq → luna → ollama`; `CRITICAL = groq → luna → sol → ollama`. Task types: `jd_extraction`, `resume_extraction`,
`question_validation`, `rubric_completion`, `rag_answer`, `analytics_summary`, `rubric_evaluation`, `career_summary`, `interview_question`, `metadata_extraction`, `ambiguous_skill_resolution`, `generic` → CHEAP;
`interview_rubric_evaluation`, `interview_pool_batch`, `hr_observation`, `aptitude_generation`, `aptitude_verification`, `question_generation`, `agent:*` → AGENT; `critical_complex_failure` → CRITICAL. Providers are used only when
configured (keys present); Ollama is always the last fallback. Timeouts: `LLM_TIMEOUT_SECONDS` (60) for cloud, `LLM_OLLAMA_TIMEOUT_SECONDS` (300) local; one schema-repair retry per provider (`LLM_MAX_RETRIES`); a 429 puts a provider
in cool-down; an OpenAI daily budget governor removes paid tiers at the hard cap. Configured on this machine: groq, luna, sol, ollama (names only). `gpt-6-*` model names in the defaults are project configuration, not verified against any
provider in this audit.

**Proctoring**: consent, system check (camera/mic/audio level/network/fullscreen), fullscreen + tab/blur/offline events, heartbeat with server-detected gaps, reviewer timeline; gate returns 428 if not started. Objective events only. RUNTIME quickfire
exercised the session lifecycle with a **simulated** preflight report. Earlier browser sessions used an injected fake camera/microphone. **A real camera/microphone has not been tested.** Screen sharing is not implemented.

**Score visibility**: a student never receives answer keys, rubrics, hidden tests, match breakdown, per-answer scores or reviewer notes (RUNTIME quickfire scans the student journey; TEST `test_score_visibility.py`). Two intentional or open points:
1. *Intentional exception*: for a round where the company configured a pass requirement, the student sees that round's score, the requirement and a plain result (`74 / 100`, "Qualified for the next round" / "Round completed"), never components or reasons.
2. *Finding, not changed*: non-student roles (including the enrolled institution) still receive the full attempt and turn payloads from `/assessments/attempts/by-application/{id}` and `/interviews/{id}/turns` (scores, rubric evaluations, question text) — CODE:
   `assessments.py` returns the recruiter-level payload when the caller is not a student. The officer UI and the pipeline journey show statuses only, but the API is broader. Whether officers should see question text/rubrics is a product decision that is open.

## 12. Frontend, tests and performance
Frontend: `npm run build` rc 0 (JS bundle 672 kB, warned as > 500 kB), `npm run lint` rc 0 (10 warnings, 0 errors), no component test suite. Backend, sequential under `scripts/memwatch.sh` (lowest free memory 28%):
| Group | Result |
|---|---|
| Default deterministic suite (unit, integration, security, agents; fake providers) | **287 passed, 15 skipped, 0 failed** |
| Judge0-dependent (`-m judge0`, real sandbox) | **11 passed** |
| Live-model (`-m live`) | **not run** (4 tests) |
| Browser | **not run in this audit** |
| Quickfire (real stack, real model calls, real Judge0) | PASS in 55 s (see `docs/QUICKFIRE_E2E.md`); degraded path verified: exit 2, coding BLOCKED, run continues |
Performance evidence: quickfire wall time 55 s; pool-served interview questions returned in < 1.5 s in tests; pipeline preparation of 5 small stages took 20 s. Larger latency traces: `docs/INTERVIEW_LATENCY.md` (earlier measurements, not re-run here).

## 13. Security notes
* Tenant isolation is enforced per resource (404 for foreign resources) and by mandatory vector-search scope; tested at API level (§8).
* Passwords are hashed; invitation and reset tokens are hashed, single-use, expiring; the email outbox exists only when `APP_ENV` is development or demo.
* Code execution is sandboxed (Judge0/isolate) and fails closed; no host fallback unless explicitly opted in.
* The quickfire and this audit stored no credentials; `.env` is not committed.
* Open: officer API breadth (§11); Judge0's Ruby 2.7/OpenSSL 1.1 layer is EOL upstream (documented in `JUDGE0_CGROUP_V2.md`) and should not be internet-exposed.

## 14. Known blockers and limitations (currently true)
* Judge0 stops executing after ~1000 submissions until reset (`scripts/judge0_reset_ids.sh`); no permanent fix.
* No real-device proctoring test; screen sharing not implemented.
* Real Whisper transcription not exercised in this audit.
* No frontend component test suite; no browser test in this audit.
* A published hiring process is frozen (a change means a new job); thresholds/weights are editable after publish.
* Aptitude/HR questions have no platform banks beyond the curated HR set; they are de-duplicated by content hash only.
* Provider rate limits (Groq 429) push work to the next provider; behaviour is covered by tests, output quality varies by model.
