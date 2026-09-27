# Architecture

```
                         ┌───────────────────────────┐
                         │   React/Vite frontend      │
                         │ (student/company/inst/admin)│
                         └──────────────┬────────────┘
                                        │ REST (TanStack Query)
                         ┌──────────────▼────────────┐
                         │        FastAPI app         │
                         │  api/v1  →  services  →    │
                         │  repositories → PostgreSQL  │
                         └───┬─────────────┬──────────┘
                             │             │
                    ┌────────▼──┐   ┌──────▼────────┐
                    │  Celery    │   │  AI Gateway    │
                    │  workers   │   │ (single choke  │
                    │ (Valkey)   │   │  point for LLM/│
                    └───┬────────┘   │  embed/rerank) │
                        │            └──────┬─────────┘
              ┌─────────┼───────────────────┼─────────┐
              │         │                   │         │
         ┌────▼───┐ ┌───▼────┐        ┌─────▼────┐┌───▼────┐
         │Postgres│ │ Judge0 │        │  Ollama   ││ Qdrant │
         │(source │ │ (code  │        │ (Qwen3.5) ││(vectors)│
         │of truth)│ execution)│      └───────────┘└────────┘
         └────────┘ └────────┘
```

## Layering

Every feature follows `API route → service → repository/model → database`. Routes only handle
auth, validation, and shaping responses; business rules (blueprint allocation, skill scoring,
matching, application state transitions) live in `app/services/*` as plain functions that take an
`AsyncSession` and return typed results, so they're testable without spinning up FastAPI.

## Why an AI Gateway

`app/services/ai_gateway/gateway.py` is the only module that knows the backing provider is Ollama.
It exposes `generate`, `generate_structured`, `extract_structured`, `evaluate_rubric`, plus
embedding/rerank helpers in the same package. Every other service and agent calls through it. To
move to production, only this package changes (see `docs/PRODUCTION_SCALING.md`) — no business
logic depends on Ollama's HTTP shape.

## Multi-tenancy

Company-private data (`questions`, `documents`, and Qdrant payloads) always carries
`organization_id`/`visibility`. Every read path that could span tenants
(`search_existing_questions`, Qdrant `search`) filters explicitly — see
`app/services/assessments/generator.py::search_existing_questions` and
`app/services/ai_gateway/vector_store.py::search`, which requires a `tenant_filter` argument by
convention.

## Data flow at a glance

See `docs/DATA_FLOW.md` for the JD → assessment → evidence → match pipeline in detail.
