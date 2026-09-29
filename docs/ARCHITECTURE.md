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

## AI Gateway and task router

```
task_type ─▶ router (providers.route) ─▶ [groq gpt-oss-120b | openai gpt-6-luna | (gpt-6-sol, escalation only) | ollama qwen3.5:4b]
                 ▲ budget governor (tracked OpenAI spend from ai_runs)
```
See `docs/AI_ROUTING_AND_COST.md`. Local models (BGE-M3, BGE reranker, faster-whisper) stay in-process,
lazy and fp16 on Apple Silicon. No large generative model needs to be resident in normal mode.

## Why an AI Gateway

`app/services/ai_gateway/` is the only package that knows which providers exist (Groq, OpenAI, Ollama).
It exposes `generate`, `generate_structured`, `extract_structured`, `evaluate_rubric`, `embed`,
`rerank`, `transcribe`; the agents get their PydanticAI models from the same router. Every other service and agent calls through it. To
move to production, only this package changes (see `docs/PRODUCTION_SCALING.md`) — no business
logic depends on any provider's HTTP shape.

## Multi-tenancy

Company-private data (`questions`, `documents`, and Qdrant payloads) always carries
`organization_id`/`visibility`. Every read path that could span tenants
(`search_existing_questions`, Qdrant `search`) filters explicitly — see
`app/services/assessments/generator.py::search_existing_questions` and
`app/services/ai_gateway/vector_store.py::search`, which requires a `tenant_filter` argument by
convention.

## Data flow at a glance

See `docs/DATA_FLOW.md` for the JD → assessment → evidence → match pipeline in detail.

## Proctoring and score visibility
- `app/services/proctoring` + `app/api/v1/proctoring.py`: sessions, events, server-side heartbeat gap
  detection, a 428 `PROCTORING_REQUIRED` gate on assessment/interview start. Frontend:
  `features/proctoring` (consent → system check → fullscreen → monitoring). See [PROCTORING.md](PROCTORING.md).
- Student responses are separate DTOs (`app/schemas/student_views.py`); reviewer access is resource-level
  (`assert_can_view_application`). See [SCORE_VISIBILITY.md](SCORE_VISIBILITY.md).
- Interview questions are spoken by the browser (`speechSynthesis`); no server audio.
