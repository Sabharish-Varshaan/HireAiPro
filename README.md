# HireAiPro

An AI-powered academia–industry skill and placement intelligence platform. It connects a shared,
canonical skill taxonomy across four portals — **student**, **company/recruiter**, **institution**,
and **platform admin** — so that a claimed skill on a resume, a JD requirement, an assessment
question, and a candidate's evidence all speak the same language.

The core lifecycle:

```
Student profile → Skill discovery → Assessment → Evidence → Skill estimation
→ AI interview → Job matching → Skill gap → Learning roadmap → Placement
```

Everything on this path is a real, working pipeline: JD text is actually sent to a local LLM for
structured extraction, questions are actually generated and validated, code is actually executed
in Judge0, skill levels are computed by a deterministic formula over stored evidence, and matches
are explainable from stored numbers — not hardcoded demo values. See
[`docs/AI_RULES.md`](docs/AI_RULES.md) for exactly what the AI is and isn't allowed to decide.

## Architecture

```
React/Vite ─▶ FastAPI (route → service → Postgres)
               ├─ Celery + Valkey (JD/resume/knowledge/assessment/matching jobs, idempotent)
               ├─ AI Gateway task router ─▶ Groq gpt-oss-120b (agents) · OpenAI gpt-6-luna (simple tasks)
               │                           · Ollama qwen3.5:4b (offline fallback) — with a daily cost governor
               ├─ Local models: BGE-M3 + BGE reranker (fp16) → Qdrant (tenant-filtered), faster-whisper
               └─ Judge0 (opt-in; labelled local fallback on macOS)
```
Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/AI_ROUTING_AND_COST.md`](docs/AI_ROUTING_AND_COST.md).

## Quickstart

Full instructions and run modes (recommended / free-first / offline): [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

```bash
docker compose up -d postgres valkey qdrant
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example .env        # set JWT_SECRET; GROQ_API_KEY / OPENAI_API_KEY are optional
.venv/bin/alembic upgrade head
.venv/bin/python -m app.services.skills.seed && .venv/bin/python -m app.services.career.seed_resources
.venv/bin/python -m app.cli create-admin you@example.com "Your Name"
.venv/bin/uvicorn app.main:app --port 8020                  # terminal 1
.venv/bin/celery -A app.workers.celery_app worker --pool=solo \
  -Q documents,assessments,matching,knowledge,reports,celery   # terminal 2
cd ../frontend && npm install && npm run dev                  # terminal 3 → http://localhost:5173
```

## Tests

```bash
cd backend
.venv/bin/pytest -q                          # 103 deterministic tests
.venv/bin/pytest -q -m live                  # 4 live-model tests (fractions of a cent)
.venv/bin/python scripts/e2e_full_scenario.py   # fresh E2E + provider/cost report
```

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design
- [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) — end-to-end pipelines
- [`docs/AI_RULES.md`](docs/AI_RULES.md) — what AI may/may not decide, and where that's enforced in code
- [`docs/SCORING.md`](docs/SCORING.md) — skill_scoring_v1 and matching_v1 formulas
- [`docs/AGENTS.md`](docs/AGENTS.md) — the four PydanticAI agents
- [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) — detailed setup + troubleshooting
- [`docs/PRODUCTION_SCALING.md`](docs/PRODUCTION_SCALING.md) — what changes to go from Ollama/local to vLLM/production
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — verified status + test totals
- [`docs/GAP_CLOSURE.md`](docs/GAP_CLOSURE.md) — requirement-by-requirement audit
- [`docs/AI_ROUTING_AND_COST.md`](docs/AI_ROUTING_AND_COST.md) — router, fallback, cost governor, pricing
- [`docs/RAG.md`](docs/RAG.md), [`docs/RAG_SECURITY.md`](docs/RAG_SECURITY.md) — retrieval and tenant isolation
- [`docs/QUESTION_GOVERNANCE.md`](docs/QUESTION_GOVERNANCE.md) — question lifecycle and import formats
- [`docs/PRIVACY_AND_DATA.md`](docs/PRIVACY_AND_DATA.md) — stored data, deletion, remote inference
