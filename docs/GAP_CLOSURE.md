# Gap Closure Audit

Audited against code and a live runtime check at the start of pass 2, not against the previous
docs. Status values: **DONE**, **PARTIAL**, **MISSING**, **BLOCKED**. The "Implementation status"
column is updated as each gap closes.

## Findings from the audit that the previous docs got wrong

- **RAG was never executed.** Qdrant had zero collections at audit time. BGE-M3 and the reranker
  had never been downloaded.
- **`vector_store.search` was broken.** It calls `QdrantClient.search`, which no longer exists in
  the installed `qdrant-client` 1.19.1 (replaced by `query_points`). It would have crashed on first
  use.
- **None of the four "agents" were PydanticAI agents.** `model_factory.py` built a PydanticAI model,
  but nothing used it. All four were plain async functions.
- **Tenant leaks in the API.** `GET /evidence/students/{id}/*` let any authenticated user read any
  student's evidence. `GET /applications/job/{id}`, `GET /matching/jobs/{id}/ranked` and
  `POST /matching/applications/{id}/compute` let any recruiter read another company's candidates.
  `PUT /jobs/{id}/requirements/confirm`, `POST /jobs/{id}/process` and assessment generate/publish
  didn't check organization membership.
- **Audit/AI-run logging was nearly absent.** One `AuditEvent` write (requirements confirm), and one
  `AIRun` write (JD extraction). Rubric scoring, question generation, resume parsing and interview
  calls weren't logged.
- **Idempotency.** Resume re-processing duplicated `RESUME_CLAIM` evidence. Re-submitting an attempt
  duplicated MCQ/technical evidence. Re-running generation created a second assessment.
- **Port conflict.** An unrelated local app now owns port 8010, so the API moved to **8020**.

## Gap table

| Requirement | Current status (at audit) | Evidence / location | Missing work | Implementation status | Verification test |
|---|---|---|---|---|---|
| Core vertical (JD→match→roadmap) | DONE | commit `f15c410`, pass-1 e2e trace | none | DONE | `tests/e2e/run_full_scenario.py` (fresh data) |
| BGE-M3 embeddings executed | MISSING | `services/ai_gateway/embeddings.py` never run | load once, embed chunks/queries | DONE | `tests/integration/test_rag_pipeline.py` |
| Reranker service | PARTIAL | `rerank()` fn, never run | `RerankerService.rerank(query, candidates, top_n)` over retrieved candidates only | DONE | same |
| Knowledge source model w/ provenance | MISSING | no table | `knowledge_sources` + `knowledge_chunks` tables, statuses, content hash | DONE | same |
| Knowledge Agent (real PydanticAI) | MISSING | plain function | Agent with get_skill/register/fetch/extract/chunk/embed/store/mark_ready tools | DONE | `tests/agents/test_agents.py` |
| RAG → Qwen grounded output w/ provenance | MISSING | DONE | retrieve→rerank→generate w/ `source_refs` | DONE | `test_rag_pipeline.py` |
| Qdrant query API | BROKEN | `vector_store.search` uses removed `.search` | port to `query_points` | DONE | same |
| Tenant-safe Qdrant filters (OR logic) | PARTIAL | AND-only `must` filter | `should` of (public) OR (private AND org) | DONE | `tests/security/test_tenant_isolation.py` |
| Qdrant payload indexes | MISSING | DONE | index organization_id, institution_id, visibility, skill_ids, document_id, source_type | DONE | inspect collection info in test |
| Cross-tenant API security | PARTIAL | leaks listed above | membership checks on every org-scoped route | DONE | `test_tenant_isolation.py` |
| Question lifecycle incl. ACTIVE/REJECTED | PARTIAL | approve/reject/retire exist, no activate/validate/promote; approve auto-publishes AI questions | explicit transitions, separate admin-only promote-to-platform | DONE | `tests/test_question_governance.py` |
| Duplicate detection via embeddings | MISSING | DONE | embedding similarity check before insert | DONE | same |
| QB import: manual/paste/CSV/JSON | PARTIAL | JSON body import only | CSV + JSON file upload, paste, rubric gen if missing | DONE | same |
| Learning resources | MISSING | table empty | 50–100 curated official resources | DONE | `tests/test_career.py` |
| Career roadmap w/ real resource IDs | PARTIAL | resources null | retrieval + multi-resource steps | DONE | same |
| Taxonomy ≥300 skills | PARTIAL | 220 skills | expand + aliases + relationships | DONE | `tests/test_skill_normalizer.py` |
| faster-whisper STT | MISSING | not wired | `SpeechToTextService` + endpoint + frontend recorder | DONE | `tests/integration/test_speech.py` |
| 4 real PydanticAI agents | MISSING | see above | real tools, typed deps/output, agent_run logging | DONE | `tests/agents/test_agents.py` |
| Interview prioritization | DONE (deterministic) | `services/interviews/selector.py` | tests for high-confidence deprioritization | DONE | `tests/test_interview_selector.py` |
| Celery idempotency | PARTIAL | JD task deletes unconfirmed rows first; resume/evidence/generation not idempotent | unique keys + upserts | DONE | `tests/integration/test_idempotency.py` |
| Audit events | PARTIAL | 1 action logged | all listed actions | DONE | `tests/test_audit.py` |
| AI run logging | PARTIAL | JD only | log inside the gateway for every call | DONE | same |
| Agent run logging | PARTIAL | assessment only | all four agents | DONE | `test_agents.py` |
| Admin portal UI | PARTIAL | counts + run lists only | skills, questions, knowledge, runs, failed jobs, audit screens | DONE | browser check |
| Institution portal UI | PARTIAL | industry demand only | roster, filters, heatmap, gaps, funnel | DONE | browser check |
| Application pipeline UI | PARTIAL | status badge only | recruiter actions + history, student timeline | DONE | browser + `test_application_state_machine.py` |
| Notifications | MISSING | table only | writes on events + UI | DONE | `tests/test_notifications.py` |
| Evidence/match explainability UI | PARTIAL | dashboard bars only | skill drilldown, recruiter match detail | DONE | browser check |
| Privacy/data export/delete | MISSING | DONE | `GET /me/data`, delete resume/transcripts, doc | DONE | `tests/test_privacy.py` |
| Frontend quality (UUIDs, empty/error states) | PARTIAL | several raw UUIDs | pass over all portals | DONE | browser check |


## Pass 3 — router, cost control, RAM (2026-09-28)
| Requirement | Status | Evidence |
|---|---|---|
| `.env` audited without printing secrets | DONE | keys reported configured/missing only; duplicate `LLM_PROVIDER` removed; Ollama URL corrected to native 11435 |
| Model ids verified against providers | DONE | Groq `/models` lists `openai/gpt-oss-120b`; OpenAI `/v1/models/{id}` 200 for gpt-6-luna/sol and gpt-5.6-luna/sol; user chose gpt-6-* (half price) |
| Task-aware router | DONE | `providers.TASK_POLICY`, test_router B, C, H |
| Budget governor (soft/hard/reserve) | DONE | test_router F, G, G2; admin endpoint |
| No retry storms / correct fallback classes | DONE | test_router D, E, J, schema-retry test |
| ai_runs usage + cost | DONE | test_cost_is_recorded…, E2E cost report |
| Agent request limits | DONE | runaway-loop test; live runs within 6 |
| Luna as agent fallback | DONE (bug found + fixed) | gpt-6-luna needs `reasoning_effort: none` with tools; forced live check passed |
| RAM reduction | DONE | Judge0 off by default (−2.3 GB), BGE fp16 (5.34 → 2.32 GB), no resident generative model |
| MLX experiment | REMOVED per instruction | venv + model files deleted |
| Admin self-registration hole | FIXED | signup refuses PLATFORM_ADMIN; `python -m app.cli create-admin` |
