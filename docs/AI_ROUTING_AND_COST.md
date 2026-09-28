# AI Routing and Cost

## Principle

1. Deterministic answer exists → no LLM (Python / SQL / BGE / Judge0).
2. Simple structured task → **OpenAI `gpt-6-luna`** (cheap, reliable JSON).
3. Complex tool-using agent → **Groq `openai/gpt-oss-120b`** (free tier).
4. Provider failure → next tier; **local Ollama `qwen3.5:4b`** is the last resort.
5. **`gpt-6-sol`** is never a default; only explicit escalation on `critical_complex_failure`.

Business code passes a `task_type`; it never names a provider.
Implementation: `backend/app/services/ai_gateway/providers.py` (policy + router),
`gateway.py` (calls, retries, fallback, usage), `budget.py` (governor), `pricing.py` (prices).

## Never an LLM

Skill normalization (exact/alias/fuzzy), assessment blueprint, MCQ scoring, code correctness,
skill estimation, evidence weighting, matching, application state machine, SQL analytics, gap
calculation, Qdrant retrieval, BGE-M3 embeddings, BGE reranking, Whisper, authorization, tenant
filtering, audit, idempotency.

## Task policy

| task_type | chain |
|---|---|
| jd_extraction, resume_extraction, question_validation, rubric_completion, rag_answer, analytics_summary, rubric_evaluation, career_summary, interview_question, metadata_extraction, ambiguous_skill_resolution | luna → groq → ollama |
| question_generation, agent:assessment_agent, agent:interview_agent, agent:career_agent, agent:knowledge_agent | groq → luna → ollama |
| critical_complex_failure | groq → luna → **sol (only with `escalate=True`)** → ollama |

Providers without a key are skipped (`*_not_configured` note). `LOCAL_ONLY=true` → `[ollama]`.

## Fallback rules

Advance to the next tier **only** on: timeout, connection error, HTTP 404 (model unavailable),
413 (provider request-size / TPM cap — Groq free tier), 429, 5xx.

- **429**: the provider enters a cool-down (`Retry-After`, capped at 120 s, default 20 s) and is
  skipped by later routes in that process — no hammering, no waiting inside a user request.
- **Schema-invalid output**: exactly one repair retry on the same provider (`LLM_MAX_RETRIES=1`),
  then the next tier once. Worst case for a paid call: Luna ×2.
- **Our own bugs** (AttributeError, integrity errors, a 400/401 we caused) are **not** masked by
  switching providers; they raise (`tests/unit/test_router.py::test_j_*`).

Agents (PydanticAI) get a `FallbackModel` over the same chain with the same failure rules.

## Cost governor (tracked estimate, not the account balance)

The OpenAI inference API doesn't expose the prepaid balance, so the app tracks its **own** spend:
every call writes `ai_runs.{input_tokens, cached_input_tokens, output_tokens, estimated_cost_usd}`.
`get_openai_spend_today()` sums today's (UTC) OpenAI rows.

| Setting | Default | Effect |
|---|---|---|
| `OPENAI_DAILY_SOFT_LIMIT_USD` | 0.25 | cheap tasks reorder to groq-first; Sol disabled |
| `OPENAI_DAILY_HARD_LIMIT_USD` | 0.35 | OpenAI removed from every chain (`OPENAI_DAILY_BUDGET_EXHAUSTED`) |
| `OPENAI_STARTING_BUDGET_USD` | 6.50 | known balance at setup |
| `OPENAI_RESERVE_USD` | 3.00 | when `starting − tracked_total ≤ reserve`, OpenAI is blocked (`OPENAI_RESERVE_REACHED`) |

At the hard cap the app keeps working on Groq → Ollama.

## Pricing (per 1M tokens, standard short context)

Source: developers.openai.com/api/docs/pricing, fetched **2026-09-27** — edit only `pricing.py`.

| Model | Input | Cached input | Output |
|---|---|---|---|
| gpt-6-luna | $0.10 | $0.01 | $0.50 |
| gpt-6-sol | $2.00 | $0.20 | $10.00 |
| gpt-5.6-luna | $0.20 | $0.02 | $1.20 |
| gpt-5.6-sol | $4.00 | $0.40 | $20.00 |

Model choice: `gpt-6-*` (already in `.env`, verified available via `GET /v1/models/{id}`, half the
price of `gpt-5.6-*`). Groq and Ollama are recorded at $0.

## Agent request budgets

`LLM_MAX_AGENT_TURNS=6` model requests per agent run (all four agents are the complex class;
`NORMAL_AGENT_REQUEST_LIMIT=4` for any simpler agent). When the budget stops a run, success is
decided by tool-persisted state; unfinished work is completed by the deterministic fallback.
Tool usage for a stopped run is still recorded (caller-owned `RunUsage`).

## Measured

| Check | Result |
|---|---|
| Luna structured extraction | 1.5 s, 109 in / 34 out, $0.0000279 |
| Groq gpt-oss-120b structured | 0.57 s, $0 |
| Luna as agent model (interview, forced) | 4 tool calls, no fallback, $0.00047 |
| Ollama qwen3.5:4b (LOCAL_ONLY) | 6.8 s, correct; unloaded after |
| Fresh E2E, Groq healthy (run 1) | 26/26 steps, **$0.0025** OpenAI (15 Luna, 16 Groq calls) |
| Fresh E2E, Groq rate-limited all run (final) | 26/26 steps, **$0.0090** OpenAI (29 Luna, 2 Groq) |

At ~$0.01 per complete recruiter+student+institution scenario, the $0.25/day soft cap allows ~25
full E2E runs per day; the $3.50 spendable before reserve covers far more than 10 days of demo use.

## Prompt layout / context

Stable rules + JSON schema go in the system prompt; dynamic data (JD, answer, retrieved chunks)
last — cache-friendly for OpenAI. Inputs are trimmed to `LLM_CONTEXT_CHARS` (head+tail). RAG sends
the reranked top 3–5 chunks, never all retrieved candidates.

## Privacy of remote inference

Groq and OpenAI receive the prompt/context of the tasks routed to them (e.g. JD text, resume text,
answers being graded, retrieved chunks). Tenant filtering happens **before** context is assembled,
so another tenant's content can't be included. Secrets, DB credentials and unrelated documents are
never part of prompts. For sensitive demos run `LOCAL_ONLY=true`.
