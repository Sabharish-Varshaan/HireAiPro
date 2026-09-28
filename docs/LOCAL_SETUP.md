# Local Setup (Apple Silicon, 16 GB)

## Prerequisites
Python 3.12 (not 3.14 — ML deps), Node 20+, Docker Desktop, Ollama (native install, optional).

## One-time setup
```bash
docker compose up -d postgres valkey qdrant           # Judge0 is opt-in, see below
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example .env                                # then set JWT_SECRET and optional API keys
.venv/bin/alembic upgrade head
.venv/bin/python -m app.services.skills.seed           # 491 skills, aliases, relationships
.venv/bin/python -m app.services.career.seed_resources # verifies every URL before storing
.venv/bin/python -m app.cli create-admin you@example.com "Your Name"   # admins can't self-register
cd ../frontend && npm install
```

## Run (each in its own terminal)
```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8020
cd backend && .venv/bin/celery -A app.workers.celery_app worker --pool=solo \
    -Q documents,assessments,matching,knowledge,reports,celery --loglevel=info
cd frontend && npm run dev                              # http://localhost:5173 → proxies /api to :8020
OLLAMA_HOST=127.0.0.1:11435 ollama serve                # only needed for fallback / Mode C
```
Port 8020 because another local app occupies 8010 on this machine. Postgres is on 5435 and Valkey
on 6380 to avoid clashing with other local instances.

## Run modes
| Mode | Config | Generation | RAM |
|---|---|---|---|
| **A — Recommended dev/demo** | both keys set | Luna for simple tasks, Groq for agents | lowest: no generative model resident |
| **B — Free-first** | `GROQ_API_KEY` only (or OpenAI soft-capped) | Groq, Ollama fallback | low |
| **C — Offline** | `LOCAL_ONLY=true`, no keys | Ollama qwen3.5:4b | +~3 GB while the model is loaded (unloads after 2 min idle) |

No mode requires a paid provider. Status: Admin → AI usage, or `GET /api/v1/admin/ai/providers`.

## Memory behaviour (measured on the M4 / 16 GB)
- BGE-M3 + reranker are lazy singletons, loaded **fp16** on MPS: 2.32 GB per process that uses
  them (fp32 was 5.34 GB), identical outputs (cosine ≥ 0.9998, same rerank order).
  faster-whisper `small.en` int8 adds ~0.5 GB, only in the API process, only after the first
  voice answer.
- Two processes can hold the embedding models: the API (retrieval, question validation) and the
  Celery worker (ingestion, generation). Keep the worker at **`--pool=solo`** (one process) so
  there is never a third copy. `--max-tasks-per-child` isn't available with the solo pool; restart
  the worker to release memory if needed.
- Ollama: requests use `keep_alive: 2m`, so qwen3.5:4b leaves memory 2 minutes after its last
  fallback call. Force-unload: `curl localhost:11435/api/generate -d '{"model":"qwen3.5:4b","keep_alive":0}'`.
- Judge0 (amd64 under emulation) used **2.3 GB** and can't execute code on this host anyway, so it
  is behind a Compose profile and off by default.

## Judge0
```bash
docker compose --profile judge0 up -d     # opt-in
```
On macOS Docker Desktop, Judge0 1.13.x cannot sandbox code: its `isolate` 1.8.1 needs cgroup v1 and
Docker Desktop's VM is cgroup v2 only (judge0/judge0#514). The coding endpoint then uses a clearly
labelled local fallback (`execution_backend: "local_fallback"` with the reason) — Python only,
wall-clock timeout, **no sandbox isolation**. It never claims Judge0 ran. On a Linux host with
cgroup v1 (or hybrid) Judge0 runs natively and results say `execution_backend: "judge0"`.

## Tests
```bash
cd backend
.venv/bin/pytest -q                 # deterministic suite (uses database hireai_test + Qdrant prefix test_)
.venv/bin/pytest -q -m live         # real models (Groq/OpenAI/Ollama per router); costs fractions of a cent
.venv/bin/python scripts/e2e_full_scenario.py   # fresh E2E against the running stack + cost report
```
The test database: `docker exec hireai_postgres psql -U hireai -c "create database hireai_test"`, then
`DATABASE_URL=postgresql+asyncpg://hireai:hireai@localhost:5435/hireai_test .venv/bin/alembic upgrade head`
and the two seed commands with the same `DATABASE_URL`.

## Troubleshooting
- **Groq 429 / 413**: free-tier limits. The router cools Groq down and uses Luna; check Admin → AI usage.
- **`role "hireai" does not exist`**: another Postgres owns the port on `localhost`; `lsof -iTCP:5435 -sTCP:LISTEN`.
- **Celery `not enough values to unpack`**: macOS prefork/spawn issue — use `--pool=solo`.
- **Celery `cannot rollback; the transaction is in error state`**: fixed — asyncpg connections are
  loop-bound; `app/workers/utils.py::run_async` disposes the pool per task.
- **Slow Ollama**: Qwen3 "thinks" by default; the gateway sends `think:false`. Run Ollama natively
  (Docker Desktop's Ollama is CPU-only).
