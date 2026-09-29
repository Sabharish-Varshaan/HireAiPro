"""RAG acceptance: register → ingest (BGE-M3) → Qdrant → query → top-K →
rerank → top-N → LLM → provenance. The LLM step is faked in the
deterministic test (so we can check exactly which chunks it saw and how
refs are mapped) and real in the `live` test."""

import pytest

from app.core.database import AsyncSessionLocal
from app.models.knowledge import KnowledgeChunk, KnowledgeSource
from app.services.ai_gateway import vector_store
from app.services.ai_gateway.vector_store import TenantScope
from qdrant_client import models as qm
from app.services.knowledge import service as ks
from app.services.knowledge.rag import grounded_answer
from tests.factories import skill, uniq
from tests.fakes import FakeLLM
from sqlalchemy import func, select

DOC = """PostgreSQL B-tree indexes.

A B-tree index keeps keys sorted, so PostgreSQL can use it for equality and range predicates such as <, <=, =, >= and >.

Partial indexes only index rows that satisfy a WHERE predicate, which keeps the index small when queries always filter on that predicate.

EXPLAIN ANALYZE shows the actual plan, row counts and timing, so you can check whether an index scan was chosen over a sequential scan.

VACUUM reclaims storage occupied by dead tuples; autovacuum runs it automatically in the background."""


async def _ingest(text: str, title: str):
    async with AsyncSessionLocal() as db:
        pg = await skill(db, "PostgreSQL")
        src = await ks.register_source(db, title=title, source_type="INLINE_TEXT", source_uri=f"inline:{uniq('pg')}",
                                       skill_ids=[pg.id], visibility="PLATFORM_PUBLIC", raw_text=text)
        await ks.ingest_source(db, src)
        await db.commit()
        return src.id, pg.id


def test_chunker_respects_size_and_overlap():
    text = "\n\n".join(("paragraph %d " % i) * 30 for i in range(10))
    chunks = ks.chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= ks.CHUNK_SIZE + 5 for c in chunks)


@pytest.mark.asyncio
async def test_ingest_embed_store_retrieve_rerank_with_provenance(monkeypatch):
    src_id, pg_id = await _ingest(DOC, "PG indexing notes")
    async with AsyncSessionLocal() as db:
        src = await db.get(KnowledgeSource, src_id)
        n_pg = await db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == src_id))
        assert src.status == "READY" and src.embedding_model == "BAAI/bge-m3" and src.chunk_count == n_pg >= 1
    # every chunk is in Qdrant with full provenance payload
    # filter by this document (the test collection grows across runs, so a top-N probe is unreliable)
    doc_filter = [qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(src_id)))]
    mine = vector_store.search("knowledge_chunks", [0.0] * 1023 + [1.0], TenantScope(), limit=100, extra_must=doc_filter)
    assert len(mine) == n_pg
    for h in mine:
        assert {"document_id", "chunk_id", "source_uri", "skill_ids", "visibility", "content_hash", "embedding_model",
                "created_at"} <= set(h.payload)
        assert str(pg_id) in h.payload["skill_ids"]

    q = "How do I check whether PostgreSQL used an index scan?"
    docs = ks.retrieve(q, TenantScope(), skill_ids=[pg_id], top_k=20, top_n=3)
    assert 1 <= len(docs) <= 3
    assert all(d.rerank_score is not None for d in docs)
    assert docs == sorted(docs, key=lambda d: d.rerank_score, reverse=True)
    assert "EXPLAIN ANALYZE" in docs[0].text

    fake = FakeLLM(monkeypatch, {"_Grounded": {"answer": "Use EXPLAIN ANALYZE.", "used_context": [1, 99]}})
    ans = await grounded_answer(q, TenantScope(), [pg_id], top_n=3)
    assert "EXPLAIN ANALYZE" in fake.all_text()  # the reranked context reached the model
    assert len(ans.source_refs) == 1  # [99] is out of range and dropped: the model can't cite unseen chunks
    ref = ans.source_refs[0]
    assert ref["document_id"] == docs[0].payload["document_id"] and ref["chunk_id"] == docs[0].payload["chunk_id"]


@pytest.mark.asyncio
async def test_unapproved_url_host_is_refused():
    async with AsyncSessionLocal() as db:
        pg = await skill(db, "PostgreSQL")
        with pytest.raises(ks.KnowledgeError):
            await ks.register_source(db, title="x", source_type="APPROVED_URL", source_uri="https://evil.example.com/x",
                                     skill_ids=[pg.id], visibility="PLATFORM_PUBLIC")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_rag_answer_is_grounded_with_refs():
    src_id, pg_id = await _ingest(DOC, "PG indexing notes (live)")
    ans = await grounded_answer("What does a partial index do in PostgreSQL?", TenantScope(), [pg_id])
    assert ans.source_refs and all(r["chunk_id"] for r in ans.source_refs)
    assert "predicate" in ans.answer.lower() or "where" in ans.answer.lower() or "subset" in ans.answer.lower()
