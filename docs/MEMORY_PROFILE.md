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
