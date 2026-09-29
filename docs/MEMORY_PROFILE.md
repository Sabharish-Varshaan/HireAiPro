# Memory profile — Apple M4, 16 GB unified RAM

All figures are measured. `footprint` is macOS physical footprint (includes MPS/unified-memory
allocations that RSS misses). The watchdog is `scripts/memwatch.sh LOG -- cmd` (5 s samples; kills
the command below 15 % free and reports it as FAIL / MEMORY BLOCKER).

## 1. Starting snapshot (2026-09-29 10:17, before any change this session)

| Item | Value |
|---|---|
| System free memory | 75 % |
| Swap used | 1974 MB of 3072 MB |
| Docker VM (Virtualization.framework RSS) | 3054 MB |
| FastAPI (uvicorn) | 190 MB (models released by idle unload) |
| Celery worker (solo) | 133 MB |
| Qdrant | 322 MiB / 1 GiB cap |
| Judge0 server / workers / db / redis | 196 / 203 / 33 / 5 MiB (caps 1.5 GiB / 1.5 GiB / 512 MiB / 256 MiB) |
| Postgres / Valkey | 36 / 7 MiB |
| Ollama (host) | 12 MB, no model loaded (`ollama ps` empty) |
| Largest other processes | Chrome 989 + 514 MB, Claude app ~0.9 GB |

**Unrelated stack stopped for this session:** compose project `hotd`
(`~/Library/Mobile Documents/com~apple~CloudDocs/HOTD`), containers `rpg_frontend`,
`rpg_celery_worker` (both were crash-looping), `rpg_backend`, `rpg_redis`, `rpg_db`, `rpg_ollama`.
Stopped with `docker stop` only; volumes `hotd_postgres_data`, `hotd_redis_data`,
`hotd_ollama_data` and all images kept. They have `restart: always`, so they return when Docker
restarts; restart manually with `docker start rpg_db rpg_redis rpg_backend rpg_ollama …`.
After stopping: free 75 %, Docker VM 3088 MB (they were near-idle; the main gain is no restart churn).

## 2. Measurements this session (all under `scripts/memwatch.sh`, 15 % abort threshold)

| Phase | Min free | Notes |
|---|---|---|
| Judge0 3-language matrix (38 cases, incl. 3 + 6 concurrent) | 76 % | 1 worker; Judge0 containers ≤ 502 MiB total |
| isolate / API attack batteries | 57–58 % | |
| Backend pytest (loads BGE-M3 in the test process) | 32–34 % | |
| Live provider tests | 44 % | Ollama never resident |
| Model warm-up (API + worker both warm) | 39 % | API 3.4 GB, worker 3.6 GB |
| **Browser E2E, 4 h, 330 samples** | **28 %** (10:48, assessment generation) | **0 aborts** |

E2E peaks: API 3496 MB, worker 5624 MB (assessment generation with reference-solution checks),
Qdrant 390 MiB (1 GiB cap), Judge0 502 MiB, swap 2.8–4.5 GB. Idle after release: API ~190 MB,
worker ~130 MB.

## 3. Recommended demo profile

```bash
docker compose up -d postgres valkey qdrant                 # hotd/rpg_* stack stopped
docker compose --profile judge0 up -d                       # Judge0: 1 worker, capped
cd backend
MODEL_IDLE_UNLOAD_SECONDS=1200 .venv/bin/uvicorn app.main:app --port 8020 &
MODEL_IDLE_UNLOAD_SECONDS=1200 .venv/bin/celery -A app.workers.celery_app worker --pool=solo \
  -Q documents,assessments,matching,knowledge,reports,celery &
.venv/bin/python scripts/warm_demo_models.py --email <admin email>   # ~16 s per process
```

- `MODEL_IDLE_UNLOAD_SECONDS=1200` keeps BGE-M3 + reranker warm through a 20-minute presentation
  (both warm cost ~7 GB; measured minimum 39 % free). Development default stays **300 s**.
- Whisper is not warmed (first transcription ~8 s). Ollama stays unloaded (Groq/Luna serve normal
  traffic). Keep `APP_ENV=demo` so unsandboxed code execution can never be enabled.
- Close other heavy apps (Chrome used ~1.5 GB during this run).
- Ollama fallback: `backend/.env` points at `localhost:11435`, but after the restart Ollama.app runs on
  the default `11434` — align one of them or the emergency fallback is unreachable (reported as
  `ollama: unreachable` on the admin page).
