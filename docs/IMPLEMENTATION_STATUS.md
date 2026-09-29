# Implementation Status

Verified state as of the three-role account / campus / assessment / interview pass (2026-09-29, later the same day than the previous pass). Every item marked DONE was
executed, not just coded; the evidence is noted beside it.

## Test totals (last full run, 2026-09-29, sequential under memwatch)
| Suite | Passed | Failed | Skipped* |
|---|---|---|---|
| unit (`tests/unit`) | 106 | 0 | 0 |
| integration (`tests/integration`) | 61 | 0 | 12 |
| security (`tests/security`) | 21 | 0 | 1 |
| agents (`tests/agents`) | 12 | 0 | 2 |
| **full default run** | **200** | **0** | 15 |
| Judge0 (`-m judge0`) | 11 | 0 | — |
| live providers (`-m live`) | 4 | 0 | — |

*Skipped = marker-gated live/Judge0 tests in the default run. Frontend `tsc -b` + `vite build`: clean.

Browser E2E of proctoring and voice: see [PROCTORING.md](PROCTORING.md) (AUTOMATED DEVICE SIMULATION;
real-device run NOT TESTED).

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
| Judge0 execution (Python, Node, C++) | DONE (cgroup-v2 build, fails closed) | `-m judge0` 11/11 |
| Student score privacy | DONE | [SCORE_VISIBILITY.md](SCORE_VISIBILITY.md) |
| Proctoring + reviewer timeline | DONE (simulated devices) | [PROCTORING.md](PROCTORING.md) |
| Invitations, claim, password reset, dev outbox | DONE | [ACCOUNTS.md](ACCOUNTS.md); browser E2E |
| Placement-officer student import / invite / resend / disable | DONE | E2E + `test_student_import.py` |
| Company -> institution approval -> eligible students | DONE | E2E + `test_opportunities.py` |
| Frozen assessment version, server timer, whole-assessment shuffle, mark/navigator | DONE | E2E + `test_assessment_lifecycle.py`, `test_assessment_layout.py` |
| Coding: samples + hidden tests, Run/Submit | DONE | E2E; live yield 3/3 questions accepted |
| Interview pool + budgeted scoring | DONE | [INTERVIEW_LATENCY.md](INTERVIEW_LATENCY.md) |
| Spoken interview questions | DONE | browser E2E: Replay +0 ai_runs |

## Known limitations
- Proctoring has not been exercised with a real camera/microphone (the automation browser blocks
  them); `speechSynthesis` voice availability varies by OS/browser.
- Sessions abandoned before consent (created by the earlier double-mount bug) stay as CREATED rows.
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
