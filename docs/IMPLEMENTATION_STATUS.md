# Implementation Status

Verified state as of the router / cost-control pass (2026-09-28). Every item marked DONE was
executed, not just coded; the evidence is noted beside it.

## Test totals (last full run)
| Suite | Passed | Failed | Skipped* |
|---|---|---|---|
| unit (`tests/unit`) | 74 | 0 | 0 |
| integration (`tests/integration`) | 12 | 0 | 1 |
| security (`tests/security`) | 11 | 0 | 1 |
| agents (`tests/agents`) | 6 | 0 | 2 |
| **deterministic total** | **103** | **0** | — |
| live-model (`-m live`) | 4 | 0 | — |

*Skipped = the live tests when running without `-m live`. Baseline before this pass: 86
deterministic. Added: 15 router/governor tests, 1 agent request-limit test, 1 admin self-signup test.
Frontend `tsc -b`: clean.

Fresh E2E (`scripts/e2e_full_scenario.py`): **26/26 steps**, three separate runs.

## Status by area
| Area | Status | Evidence |
|---|---|---|
| Core vertical (JD → match → roadmap) | DONE | E2E 26/26 |
| RAG (BGE-M3 → Qdrant → reranker → LLM + provenance) | DONE | test_rag_pipeline, E2E (grounded questions with source_refs) |
| Tenant-safe RAG / API | DONE | security suite 11/11 + live leak test |
| Knowledge / Assessment / Interview / Career agents (PydanticAI) | DONE | agent suite + live runs completing via LLM |
| Question governance + import | DONE | unit governance tests, E2E upload |
| Learning resources (106 verified URLs) | DONE | E2E roadmap with real resource ids |
| Taxonomy (491 skills, aliases, 185 relationships) | DONE | normalizer tests |
| faster-whisper STT | DONE | test_speech, E2E voice turn |
| Celery idempotency | DONE | test_idempotency (JD, resume, knowledge, assessment, matching) |
| Audit / ai_runs / agent_runs | DONE | E2E admin audit (21 action types), cost report |
| Notifications, privacy controls | DONE | pipeline + privacy tests, E2E |
| Institution + admin portals | DONE (API verified; UI type-checked, AI-usage panel added) | E2E institution/admin steps |
| **Task router + cost governor** | DONE | test_router A–J, live Luna/Groq/Ollama checks |
| Judge0 execution | **BLOCKED on this Mac** (cgroup v2); labelled local fallback | E2E shows `execution_backend=local_fallback` |

## Known limitations
- Judge0 can't sandbox on Docker Desktop (macOS); works on a cgroup-v1 Linux host. The local
  fallback runs real Python but without sandbox isolation.
- Groq's free tier rate-limits (429/413) under repeated test runs; the router then uses Luna (cost
  still < $0.01 per full E2E).
- Agent orchestration isn't 100% deterministic: in the final E2E 5/6 agent runs completed via the
  LLM, 1 knowledge run stopped early and the deterministic fallback finished it (correct result).
- The JD normalizer leaves compound phrases ("data structures and algorithms", "schema design")
  unmapped for recruiter review; LLM disambiguation (`ambiguous_skill_resolution`) is routed but
  not wired into the normalizer yet.
- Browser UI was type-checked this pass but not re-clicked end to end; the API paths it calls are
  exercised by the E2E script.
- `.env` still contains `LLM_PRIMARY_PROVIDER` / `LLM_CHEAP_PROVIDER` / `LLM_LOCAL_FALLBACK_PROVIDER`;
  they're parsed but the effective order is `TASK_POLICY` (documented).
