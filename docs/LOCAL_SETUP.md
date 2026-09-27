# Local Setup

## Prerequisites

- Python 3.12 (3.14 currently breaks some ML deps — use 3.12)
- Node 20+
- Docker (Postgres, Qdrant, Valkey, Judge0)
- [Ollama](https://ollama.com) installed natively (not just in Docker) so it can use Apple
  Silicon/NVIDIA GPU acceleration — the same model running inside Docker Desktop on macOS is
  CPU-only and dramatically slower.

## 1. Infra

```bash
docker compose up -d postgres valkey qdrant judge0-db judge0-redis judge0-server judge0-workers
```

Ports are intentionally non-default (5435, 6380) to avoid clashing with any other local Postgres/Redis — see `docker-compose.yml`.

## 2. Ollama

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama serve &     # run natively for GPU acceleration
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3.5:4b
```

Point `LLM_BASE_URL` at whichever host:port you ran `ollama serve` on.

## 3. Backend

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example .env   # adjust ports if you changed docker-compose.yml
.venv/bin/alembic upgrade head
.venv/bin/python -m app.services.skills.seed     # seeds the skill taxonomy
.venv/bin/uvicorn app.main:app --port 8020 --reload
```

## 4. Celery worker

```bash
cd backend
.venv/bin/celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` avoids a macOS + Python 3.12 + billiard prefork/spawn incompatibility
(`ValueError: not enough values to unpack`) seen with the default prefork pool. On Linux, prefork
works fine.

## 5. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to :8020
```

## 6. Judge0

Already started in step 1. Verify: `curl http://localhost:2358/languages`. Judge0's own container
needs `privileged: true` for its cgroup-based sandboxing — this is Judge0's standard requirement,
not something specific to this project.

## Test commands

```bash
cd backend && .venv/bin/pytest
```

## Troubleshooting

- **LLM calls take minutes**: Qwen3 models "think" by default, burning hundreds of tokens on
  chain-of-thought before answering. The AI Gateway passes `"think": false` to Ollama
  (`LLM_THINK` env var) — if you still see multi-minute calls, confirm Ollama actually picked up
  GPU offload (`ollama ps` should show `100%` GPU, not `100%` CPU).
- **`role "hireai" does not exist` connecting to Postgres on the port you expect**: another
  Postgres (Homebrew or another project's Docker container) may already be listening on that port
  and winning the bind on `localhost`. Check with `lsof -iTCP:<port> -sTCP:LISTEN` and change the
  port in `docker-compose.yml`/`.env` if so.
- **Celery task fails with `cannot rollback; the transaction is in error state`**: this was a real
  bug we hit and fixed — asyncpg connections are bound to the event loop that created them, and
  Celery's prefork/solo pool gives each task its own `asyncio.run()` (a new loop). The shared
  engine's pool must be disposed after each task; see `app/workers/utils.py::run_async`.
