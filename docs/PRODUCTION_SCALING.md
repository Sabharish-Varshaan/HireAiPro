# Production Scaling

## Inference

```
Hackathon:   FastAPI → AI Gateway → Ollama (local) → Qwen3.5
Production:  FastAPI → AI Gateway → Load Balancer → vLLM → GPU replicas
```

Only `app/services/ai_gateway/gateway.py` needs to change: swap the `httpx` call from Ollama's
`/api/generate` to an OpenAI-compatible `/v1/chat/completions` against vLLM (vLLM already speaks
that protocol), and `app/agents/model_factory.py`'s `OpenAIProvider(base_url=...)` just points at
the new endpoint. No service or agent above the gateway references Ollama, model names, or
Ollama-specific fields (`think`, `num_predict`) — those live entirely inside `gateway.py`.

## Embeddings / reranking

`app/services/ai_gateway/embeddings.py` wraps `sentence-transformers` locally. In production this
becomes its own inference service (e.g. TEI — Text Embeddings Inference) behind an HTTP call from
the same module; callers (`vector_store.py`, knowledge/question generation) don't change.

## Speech

`faster-whisper`/Kokoro run in-process today. Both are CPU/GPU-bound and would move to dedicated
inference pods behind a queue in production; the interview flow already degrades to text-only if
STT/TTS isn't configured, so this is a pure infrastructure change.

## Storage

`app/services/storage/service.py::StorageService` wraps `LocalStorageBackend`. Swapping to S3 means
writing an `S3StorageBackend` with the same `save`/`read` signature and changing one line in
`get_storage_service()` — no caller (`documents.py`, `students.py`, `jobs.py`) changes.

## Background processing

Celery + Valkey today; the same code runs against a managed Redis/RabbitMQ and a larger worker
fleet in production. Queues are already split by workload (`documents`, `assessments`, `matching`)
so they can scale independently.

## Database

PostgreSQL is the source of truth in both environments. Production adds read replicas for
analytics (`app/services/analytics/institution.py`'s aggregation queries are read-only and a good
replica candidate) without any application code change.
