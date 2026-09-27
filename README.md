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

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full diagram. In short:

```
React/Vite frontend → FastAPI (route → service → repository → Postgres)
                          ├─ Celery workers (Valkey) for JD/resume/question processing
                          ├─ AI Gateway → Ollama (Qwen3.5) — the only module that knows the provider
                          ├─ Qdrant for skill/question/knowledge embeddings (BGE-M3 + reranker)
                          └─ Judge0 for real code execution
```

## Prerequisites

- Python 3.12, Node 20+, Docker
- [Ollama](https://ollama.com) installed natively for GPU-accelerated inference

## Quickstart

Full step-by-step instructions, including known local gotchas, are in
[`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md). Short version:

```bash
# 1. Infra
docker compose up -d postgres valkey qdrant judge0-db judge0-redis judge0-server judge0-workers

# 2. Ollama (native, for GPU acceleration)
OLLAMA_HOST=127.0.0.1:11435 ollama serve &
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3.5:4b

# 3. Backend
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example .env
.venv/bin/alembic upgrade head
.venv/bin/python -m app.services.skills.seed
.venv/bin/uvicorn app.main:app --port 8020 --reload

# 4. Celery worker (separate terminal)
cd backend && .venv/bin/celery -A app.workers.celery_app worker --loglevel=info --pool=solo

# 5. Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, sign up as a **Recruiter**, create a company and a job, paste a JD,
and watch it get analyzed.

## Tests

```bash
cd backend && .venv/bin/pytest
```

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system design
- [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) — end-to-end pipelines
- [`docs/AI_RULES.md`](docs/AI_RULES.md) — what AI may/may not decide, and where that's enforced in code
- [`docs/SCORING.md`](docs/SCORING.md) — skill_scoring_v1 and matching_v1 formulas
- [`docs/AGENTS.md`](docs/AGENTS.md) — the four PydanticAI agents
- [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) — detailed setup + troubleshooting
- [`docs/PRODUCTION_SCALING.md`](docs/PRODUCTION_SCALING.md) — what changes to go from Ollama/local to vLLM/production
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — live build checklist
