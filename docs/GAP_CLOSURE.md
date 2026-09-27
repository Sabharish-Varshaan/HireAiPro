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
| BGE-M3 embeddings executed | MISSING | `services/ai_gateway/embeddings.py` never run | load once, embed chunks/queries | — | `tests/integration/test_rag_pipeline.py` |
| Reranker service | PARTIAL | `rerank()` fn, never run | `RerankerService.rerank(query, candidates, top_n)` over retrieved candidates only | — | same |
| Knowledge source model w/ provenance | MISSING | no table | `knowledge_sources` + `knowledge_chunks` tables, statuses, content hash | — | same |
| Knowledge Agent (real PydanticAI) | MISSING | plain function | Agent with get_skill/register/fetch/extract/chunk/embed/store/mark_ready tools | — | `tests/agents/test_agents.py` |
| RAG → Qwen grounded output w/ provenance | MISSING | — | retrieve→rerank→generate w/ `source_refs` | — | `test_rag_pipeline.py` |
| Qdrant query API | BROKEN | `vector_store.search` uses removed `.search` | port to `query_points` | — | same |
| Tenant-safe Qdrant filters (OR logic) | PARTIAL | AND-only `must` filter | `should` of (public) OR (private AND org) | — | `tests/security/test_tenant_isolation.py` |
| Qdrant payload indexes | MISSING | — | index organization_id, institution_id, visibility, skill_ids, document_id, source_type | — | inspect collection info in test |
| Cross-tenant API security | PARTIAL | leaks listed above | membership checks on every org-scoped route | — | `test_tenant_isolation.py` |
| Question lifecycle incl. ACTIVE/REJECTED | PARTIAL | approve/reject/retire exist, no activate/validate/promote; approve auto-publishes AI questions | explicit transitions, separate admin-only promote-to-platform | — | `tests/test_question_governance.py` |
| Duplicate detection via embeddings | MISSING | — | embedding similarity check before insert | — | same |
| QB import: manual/paste/CSV/JSON | PARTIAL | JSON body import only | CSV + JSON file upload, paste, rubric gen if missing | — | same |
| Learning resources | MISSING | table empty | 50–100 curated official resources | — | `tests/test_career.py` |
| Career roadmap w/ real resource IDs | PARTIAL | resources null | retrieval + multi-resource steps | — | same |
| Taxonomy ≥300 skills | PARTIAL | 220 skills | expand + aliases + relationships | — | `tests/test_skill_normalizer.py` |
| faster-whisper STT | MISSING | not wired | `SpeechToTextService` + endpoint + frontend recorder | — | `tests/integration/test_speech.py` |
| 4 real PydanticAI agents | MISSING | see above | real tools, typed deps/output, agent_run logging | — | `tests/agents/test_agents.py` |
| Interview prioritization | DONE (deterministic) | `services/interviews/selector.py` | tests for high-confidence deprioritization | — | `tests/test_interview_selector.py` |
| Celery idempotency | PARTIAL | JD task deletes unconfirmed rows first; resume/evidence/generation not idempotent | unique keys + upserts | — | `tests/integration/test_idempotency.py` |
| Audit events | PARTIAL | 1 action logged | all listed actions | — | `tests/test_audit.py` |
| AI run logging | PARTIAL | JD only | log inside the gateway for every call | — | same |
| Agent run logging | PARTIAL | assessment only | all four agents | — | `test_agents.py` |
| Admin portal UI | PARTIAL | counts + run lists only | skills, questions, knowledge, runs, failed jobs, audit screens | — | browser check |
| Institution portal UI | PARTIAL | industry demand only | roster, filters, heatmap, gaps, funnel | — | browser check |
| Application pipeline UI | PARTIAL | status badge only | recruiter actions + history, student timeline | — | browser + `test_application_state_machine.py` |
| Notifications | MISSING | table only | writes on events + UI | — | `tests/test_notifications.py` |
| Evidence/match explainability UI | PARTIAL | dashboard bars only | skill drilldown, recruiter match detail | — | browser check |
| Privacy/data export/delete | MISSING | — | `GET /me/data`, delete resume/transcripts, doc | — | `tests/test_privacy.py` |
| Frontend quality (UUIDs, empty/error states) | PARTIAL | several raw UUIDs | pass over all portals | — | browser check |
