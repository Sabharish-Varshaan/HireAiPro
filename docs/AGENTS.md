# Agents

Four real PydanticAI (2.51) agents: typed deps (dataclass), typed output, registered tools that
call deterministic services, `agent_runs` logging with every tool call, and a deterministic
fallback. **Tool-persisted state is authoritative**: each public agent function rebuilds its typed
result from what the tools wrote, never from numbers/IDs the model reports.

| Agent | Tools | Guards |
|---|---|---|
| Knowledge (`knowledge_agent.py`) | get_skill, get_existing_sources, register_source, fetch_source, extract_text, chunk_text, embed_chunks, store_chunks, mark_ready | approved hosts only; store_chunks completes skipped earlier steps; bad ids → ModelRetry |
| Assessment (`assessment_agent.py`) | get_job_competencies, build_assessment_blueprint, search_company_questions, search_platform_questions, retrieve_knowledge, generate_missing_question, validate_question, create_assessment | per-skill tools take a list of skill indexes; generation always searches company then platform banks first; only confirmed skills |
| Interview (`interview_agent.py`) | rank_competencies, get_job_requirements, get_student_evidence, get_interview_history, search_question_bank, retrieve_skill_knowledge, save_interview_turn | may only pick from the top-2 of the deterministic ranking; difficulty set by the selector, not the model |
| Career (`career_agent.py`) | get_target_job, get_student_skills, calculate_skill_gaps, get_skill_prerequisites, search_learning_resources, save_learning_path | drops non-gap skills and unknown resource ids; prerequisites ordered first |

## Runtime (`runtime.py`, `model_factory.py`)
- Model chosen per run by the router (`agent:<name>` → Groq → Luna → Ollama) as a `FallbackModel`
  that advances only on 404/413/429/5xx/connection errors.
- Budget: `LLM_MAX_AGENT_TURNS=6` model requests (`UsageLimits`). If the budget stops the chat,
  success is decided by persisted state; unfinished work goes to the deterministic fallback.
- Tool calls in one response run **sequentially** (tools share one AsyncSession).
- Output type is `[Model, str]` so tool_choice stays `auto` (gpt-oss sometimes wrote the final JSON
  as text under a forced output tool → Groq 400 `tool_use_failed`).
- OpenAI agent calls use `reasoning_effort: none` (gpt-6-luna rejects tools + reasoning_effort on
  chat completions). Ollama: `reasoning_effort: none` (Qwen thinking off). Groq gpt-oss: `low`.
- Token usage (even of a failed run) → `ai_runs` with provider/model/cost.

## Measured behaviour (live)
| Run | Model | Result |
|---|---|---|
| Knowledge (FastAPI docs) | Ollama qwen3.5:4b (pass 2 start) | all 9 tools, no fallback |
| Interview, Career (live tests) | Groq gpt-oss-120b | completed via LLM, no fallback |
| Interview (forced OpenAI) | gpt-6-luna | 4 tools, no fallback, $0.00047 |
| Final E2E (Groq rate-limited → Luna) | gpt-6-luna | 5 of 6 agent runs completed via LLM; 1 knowledge run fell back (model stopped early), result still correct |

Earlier failures fixed along the way: request budget too small for real traces; unbatched per-skill
calls; tool raising instead of correcting the model; Groq 413 from an oversized tool result;
gpt-6-luna tool/reasoning incompatibility.

## Tests
`tests/agents/test_agents.py` (scripted `FunctionModel`: every agent's tools execute, reconciliation,
selection boundary, fabricated resources dropped, runaway loop cut at the budget, fallback) and live
tests (`-m live`).
