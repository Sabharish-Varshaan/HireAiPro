# HireAiPro

An AI-assisted campus hiring and skill-evidence platform with three active roles: **Placement Officer** (institution), **Company / Recruiter** and **Student**. A company builds a hiring process per job
(aptitude, technical, coding, technical interview, HR interview), sets a pass threshold per round, and candidates advance only when a deterministic score crosses it. AI models score written answers and
interviews against rubrics; they never decide who advances. Audit of what is verified today: [`docs/SYSTEM_AUDIT.md`](docs/SYSTEM_AUDIT.md).

## Architecture
```
React/Vite (5173) ──/api──▶ FastAPI (8020): route → service → Postgres
                             ├─ Celery worker + Valkey: JD extraction, stage/interview-pool preparation, matching
                             ├─ AI gateway (router): Groq · OpenAI · Ollama (local fallback), spend governor
                             ├─ Local models in-process: BGE-M3 + reranker → Qdrant (tenant-scoped), faster-whisper
                             └─ Judge0 (sandboxed code execution, docker profile)
```
```
Job Configuration → Hiring Rounds → Assessment / Interview → Adaptive Agent Evaluation → Normalized Score (0–100)
   → Threshold Engine (score ≥ threshold) → Qualified? YES → next round · NO → stop / manual review (a person may advance or hold, with a reason)
```
```
Task Demand → Capability Resolver → Required Agents Only → Cost-aware Model Router → Structured Result + compact trace
```
Design docs: [architecture](docs/ARCHITECTURE.md), [hiring pipeline](docs/HIRING_PIPELINE.md), [qualification](docs/ROUND_QUALIFICATION.md), [model routing and cost](docs/AI_ROUTING_AND_COST.md).

## Run it locally from zero
Tested on macOS (Apple Silicon, 16 GB) with Docker Desktop. Linux should work the same way; Judge0 needs Docker with cgroup v2.

### 1. Prerequisites
* Docker Desktop (Compose v2), Python **3.12**, Node **22** with npm, Git.
* [Ollama](https://ollama.com) installed natively (recommended; needed when no cloud key is set).
* Free disk/RAM: the first run downloads the local embedding, reranker and speech models (a few GB, cached by Hugging Face). This project was developed with an 8 GB Docker Desktop VM; each Judge0 container is capped at 1.5 GB and Qdrant at 1 GB.
* Free ports: 5173, 8020, 5435, 6380, 6333, 6334, 2358, 11434.

### 2. Get the code
Clone this repository, then:
```bash
cd HireAiPro
```

### 3. Environment file
```bash
cp .env.example backend/.env
```
Edit `backend/.env`: **set `JWT_SECRET`** to your own long random value. Everything else has a working local default. `GROQ_API_KEY` and `OPENAI_API_KEY` are optional (without either, every model call goes to Ollama, slower). Never commit `backend/.env`. Variable reference: [`docs/SYSTEM_AUDIT.md` §3](docs/SYSTEM_AUDIT.md).

### 4. Infrastructure (Postgres, Valkey, Qdrant)
```bash
docker compose up -d postgres valkey qdrant
```

### 5. Python environment
```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 6. Database schema and seed data
```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.services.skills.seed
.venv/bin/python -m app.services.career.seed_resources
```
Verify: `.venv/bin/alembic current` must print the same revision as `.venv/bin/alembic heads` (currently `ff25cda85069`). The skill taxonomy seed is required (job requirements map onto it).

### 7. Ollama (local model)
```bash
ollama serve                 # in its own terminal; listens on 127.0.0.1:11434
ollama pull qwen3.5:4b       # the configured OLLAMA_MODEL
```

### 8. Judge0 (sandboxed coding rounds)
```bash
cd ..    # repository root
docker compose --profile judge0 up -d --build     # first build takes several minutes
```
Health check and one real run:
```bash
curl -s localhost:2358/about
curl -s -X POST "localhost:2358/submissions?base64_encoded=false&wait=false" -H 'Content-Type: application/json' -d '{"source_code":"print(6*7)","language_id":71}'
# then GET localhost:2358/submissions/<token>?base64_encoded=false  → status "Accepted", stdout "42"
```
**Known local issue.** After roughly 1000 executions Judge0 answers `Internal Error … No such file or directory @ rb_sysopen - /box/script.py` (worker log: `Sandbox ID out of range (allowed: 0-999)`): its submission counter passed isolate's box limit. Fix: `scripts/judge0_reset_ids.sh` (clears only Judge0's own execution log). Details: [`docs/SYSTEM_AUDIT.md` §6](docs/SYSTEM_AUDIT.md).

### 9. Start the API and the worker (two terminals, from `backend/`)
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8020
```
```bash
.venv/bin/celery -A app.workers.celery_app worker --pool=solo -Q documents,assessments,matching,knowledge,reports,celery --loglevel=info
```
`--pool=solo` (one task at a time) is the safe setting for a 16 GB Mac. There is no auto-reload: restart both after code changes. Local models are released after 5 idle minutes (`MODEL_IDLE_UNLOAD_SECONDS`).

### 10. Start the frontend
```bash
cd frontend && npm install && npm run dev
```
Open http://localhost:5173.

### 11. Health check
| Service | Check | Expected |
|---|---|---|
| Frontend | open http://localhost:5173 | login page |
| API | `curl -s localhost:8020/api/v1/skills \| head -c 80` | JSON list of skills |
| Postgres | `docker exec hireai_postgres pg_isready -U hireai` | accepting connections |
| Valkey | `docker exec hireai_valkey valkey-cli ping` | `PONG` |
| Qdrant | `curl -s localhost:6333/collections` | JSON `"status":"ok"` |
| Judge0 | `curl -s localhost:2358/about` and the run in step 8 | version JSON; `42` |
| Ollama | `curl -s localhost:11434/api/tags` | lists `qwen3.5:4b` |
| Worker | `.venv/bin/celery -A app.workers.celery_app inspect ping` (from `backend/`) | `pong` |
| Everything | `backend/.venv/bin/python scripts/quickfire_e2e.py` | `Overall: PASS` |

### 12. First successful walkthrough
1. Open `/signup`, create a **Placement Officer** (this creates the institution). In *Academic structure* add a department and a cohort.
2. *Students* → invite a student. There is no mail provider locally: open `/dev/outbox` (only when `APP_ENV` is `development`/`demo`), copy the claim link, open it and choose a password.
3. Sign out. Sign up a **Recruiter** with a company name. Create a job (type, work mode, location, deadline), paste a job description, *Extract Requirements*, fix any unmapped skill, *Confirm requirements*.
4. *Hiring Process* tab: switch on the rounds you want, set duration, question count and each round's **pass threshold**, press *Save*, then *Generate/Prepare* each round (the worker does this), and *Publish hiring process*.
5. Under *Overview → Candidate distribution* target your institution (do this before publishing). The officer sees the opportunity under *Opportunities*, chooses department/cohort/year and approves.
6. The student signs in, sees the job, applies, and works through the rounds (a consented system check is required for proctored rounds; use a normal Chrome/Safari window).
7. The recruiter opens the job → *Candidates* → a candidate: *Status & Decision* shows each round's score, requirement, result and any override.

### 13. Common commands
| Task | Command |
|---|---|
| Backend tests (deterministic) | `cd backend && .venv/bin/pytest -q` (needs the test database, below) |
| Judge0-dependent tests | `.venv/bin/pytest -q -m judge0` |
| Live-model tests | `.venv/bin/pytest -q -m live` (needs a working model; small cost) |
| Quickfire E2E | `backend/.venv/bin/python scripts/quickfire_e2e.py` ([`docs/QUICKFIRE_E2E.md`](docs/QUICKFIRE_E2E.md)) |
| Frontend build / lint | `cd frontend && npm run build && npm run lint` |
| Migrations | `.venv/bin/alembic upgrade head` (dev DB); status: `.venv/bin/alembic current` |
| Service status | `docker compose ps` and `docker ps` |
| Logs | `docker logs -f hireai_judge0_workers` · the API and worker terminals |
Test database (once): `docker exec hireai_postgres psql -U hireai -c "create database hireai_test"`, then run the three commands of step 6 with `DATABASE_URL=postgresql+asyncpg://hireai:hireai@localhost:5435/hireai_test` in front. Tests use Valkey db 10 and Qdrant prefix `test_`; run heavy suites one at a time (`scripts/memwatch.sh LOG -- <command>` aborts before memory runs out).

### 14. Stop (data is kept)
Stop the API, worker and Vite with Ctrl-C, then:
```bash
docker compose stop            # keeps all data volumes
```
Stop Ollama with Ctrl-C in its terminal (it unloads its model).

### 15. Full reset (deletes local data)
**Destructive**: this deletes the Postgres, Qdrant and Judge0 data volumes (all local accounts, jobs, questions, results).
```bash
docker compose --profile judge0 down -v
```
Then start again from step 4.

## Roles, accounts and privacy
Placement Officer signs up with an institution, manages departments and cohorts, invites or imports students and approves company opportunities. Recruiter signs up with a company. Students are invited and claim
their account with their own password; forgot/reset password is supported. No default or shared passwords. See [accounts](docs/ACCOUNTS.md), [privacy](docs/PRIVACY_AND_DATA.md).
Proctoring records objective events only (no recording, no cheating score): [proctoring](docs/PROCTORING.md). Students never receive answer keys, rubrics or per-answer scores; the one exception is the company-configured round
result (score, requirement, outcome): [score visibility](docs/SCORE_VISIBILITY.md).

## Documentation
[System audit](docs/SYSTEM_AUDIT.md) · [Quickfire E2E](docs/QUICKFIRE_E2E.md) · [Architecture](docs/ARCHITECTURE.md) · [Hiring pipeline](docs/HIRING_PIPELINE.md) · [Round qualification and agents](docs/ROUND_QUALIFICATION.md) ·
[Job posting](docs/JOB_POSTING.md) · [Question import](docs/QUESTION_IMPORT.md) · [Interview latency](docs/INTERVIEW_LATENCY.md) · [Judge0](docs/JUDGE0_CGROUP_V2.md) · [Memory profile](docs/MEMORY_PROFILE.md) ·
[Scoring](docs/SCORING.md) · [AI rules](docs/AI_RULES.md) · [RAG security](docs/RAG_SECURITY.md).

## Known limitations
No real-camera proctoring test yet and no screen sharing; Judge0 needs a periodic id reset (step 8); real Whisper transcription is not covered by the quickfire; no frontend component tests. Full list: [`docs/SYSTEM_AUDIT.md` §14](docs/SYSTEM_AUDIT.md).
