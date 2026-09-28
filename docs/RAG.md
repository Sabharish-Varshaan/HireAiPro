# RAG

```
approved source ─▶ Knowledge Agent ─▶ fetch (allowlisted host / local seed / inline) ─▶ extract text
  ─▶ chunk (~900 chars, 150 overlap, paragraph-aware) ─▶ BGE-M3 (fp16) ─▶ Postgres knowledge_chunks
  + Qdrant knowledge_chunks (point id = chunk id)

query ─▶ BGE-M3 ─▶ Qdrant top-K (≈20–30, tenant filter applied inside the query)
      ─▶ BGE reranker v2-m3 (only those K) ─▶ top-N (3–5) ─▶ LLM (router) ─▶ answer + source_refs
```

- **Provenance**: the LLM sees numbered blocks and returns the numbers it used; they are mapped
  back to real `(document_id, chunk_id, source_uri, visibility, rerank_score)`. Out-of-range numbers
  are dropped — the model can't cite a chunk it wasn't shown. (`app/services/knowledge/rag.py`)
- **Sources** (`knowledge_sources`): title, source_type, source_uri, org/institution, visibility,
  skill_ids, status (REGISTERED/PROCESSING/READY/FAILED/STALE), content_hash, document_version,
  chunk_count, embedding_model, last_ingested_at, error.
- **No crawling**: `APPROVED_URL` only fetches the exact URL an admin registered, only from
  official-docs hosts in `APPROVED_HOSTS`; links are not followed.
- **Idempotent**: unique (uri, tenant); unchanged content (same hash, READY) is skipped; changed
  content replaces the document's chunks in both stores.
- **Grounded generation**: assessment questions retrieve tenant-scoped chunks for the skill and
  store `source_refs`; the validator checks the question is supported by those chunks (reranker
  score ≥ 0.3).

Verified: `tests/integration/test_rag_pipeline.py` (deterministic + live), E2E (official
PostgreSQL docs page → 9 chunks, reranked top score 0.98, RAG-grounded generated questions).
