"""Company A's private question and private knowledge must be invisible to
Company B through the API, through raw Qdrant retrieval, and in the context
handed to the LLM — while Company A can still retrieve both."""

import uuid

import pytest
import pytest_asyncio

from app.core.database import AsyncSessionLocal
from app.models.enums import UserRole
from app.models.knowledge import KnowledgeSource
from app.services.ai_gateway import vector_store
from app.services.ai_gateway.embeddings import get_embedding_service
from app.services.ai_gateway.vector_store import TenantScope
from app.services.knowledge import service as ks
from app.services.knowledge.rag import grounded_answer
from tests.factories import make_company, make_user
from tests.fakes import FakeLLM

SECRET = "A_SECRET_FASTAPI_CONCEPT_123"
# Appears ONLY inside Company A's private document body — never in any
# question, query or public document — so its presence anywhere downstream of
# a Company B request can only mean a real leak.
PRIVATE_ONLY = "A_SECRET_RETRY_DECORATOR_9831"
PRIVATE_DOC = (
    f"Internal FastAPI playbook. {SECRET}: every FastAPI dependency in our payments service must be declared "
    f"with Depends and wrapped in our custom retry decorator {PRIVATE_ONLY} before being injected into a path operation. "
    "This convention is confidential to the company and must never be shared outside it.\n\n"
    "Dependencies in FastAPI can also be classes; FastAPI calls them and injects the returned instance."
)
PUBLIC_DOC = (
    "FastAPI dependency injection: declare a dependency by adding a parameter with Depends(callable). "
    "FastAPI calls the dependency for each request and passes the result to the path operation function.\n\n"
    "Dependencies can depend on other dependencies, forming a graph that FastAPI resolves automatically."
)


@pytest_asyncio.fixture
async def tenants(client):
    async with AsyncSessionLocal() as db:
        org_a, rec_a, ha = await make_company(db, "A")
        org_b, rec_b, hb = await make_company(db, "B")
        _, hadmin = await make_user(db, UserRole.PLATFORM_ADMIN)
        await db.commit()

    # A's private question, through the real import pipeline (validator + Qdrant index)
    r = await client.post("/questions", headers=ha, json={
        "question_text": f"In our codebase, what does {SECRET} require for every FastAPI dependency?",
        "question_type": "TECHNICAL", "skill": "FastAPI", "difficulty": "medium",
        "expected_concepts": ["Depends", "retry decorator"], "rubric": {"criteria": ["mentions Depends", "mentions retry"]},
        "organization_id": str(org_a.id)})
    assert r.status_code == 200, r.text
    q_id = r.json()["question_ids"][0]

    # A's private knowledge document and a platform-public one, ingested for real (BGE-M3 + Qdrant)
    ids = {}
    for label, headers, body in (
        ("private", ha, {"title": "A internal FastAPI playbook", "source_type": "INLINE_TEXT", "text": PRIVATE_DOC,
                         "skills": ["FastAPI"], "visibility": "COMPANY_PRIVATE", "organization_id": str(org_a.id), "ingest": False}),
        ("public", hadmin, {"title": "FastAPI DI basics", "source_type": "INLINE_TEXT", "text": PUBLIC_DOC,
                            "skills": ["FastAPI"], "visibility": "PLATFORM_PUBLIC", "ingest": False}),
    ):
        r = await client.post("/knowledge/sources", headers=headers, json=body)
        assert r.status_code == 200, r.text
        ids[label] = uuid.UUID(r.json()["id"])
    async with AsyncSessionLocal() as db:
        for sid in ids.values():
            await ks.ingest_source(db, await db.get(KnowledgeSource, sid))
        await db.commit()
    return {"org_a": org_a, "org_b": org_b, "ha": ha, "hb": hb, "q_id": q_id, "doc_id": str(ids["private"])}


@pytest.mark.asyncio
async def test_private_question_isolation_api(client, tenants):
    t = tenants
    b_list = (await client.get("/questions", headers=t["hb"])).text
    assert SECRET not in b_list
    assert (await client.get(f"/questions/{t['q_id']}", headers=t["hb"])).status_code == 404
    assert (await client.post(f"/questions/{t['q_id']}/approve", headers=t["hb"])).status_code == 404
    assert SECRET in (await client.get("/questions", headers=t["ha"])).text
    assert (await client.get(f"/questions/{t['q_id']}", headers=t["ha"])).status_code == 200


@pytest.mark.asyncio
async def test_private_question_isolation_qdrant(tenants):
    vec = get_embedding_service().embed([f"{SECRET} FastAPI dependency retry decorator"])[0]
    b = vector_store.search("questions", vec, TenantScope(organization_id=tenants["org_b"].id), limit=50)
    assert all(SECRET not in d.text for d in b)
    assert all(d.payload.get("organization_id") in (None, str(tenants["org_b"].id)) for d in b)
    a = vector_store.search("questions", vec, TenantScope(organization_id=tenants["org_a"].id), limit=50)
    assert any(SECRET in d.text for d in a)


@pytest.mark.asyncio
async def test_private_knowledge_isolation_api(client, tenants):
    t = tenants
    assert SECRET not in (await client.get("/knowledge/sources", headers=t["hb"])).text
    b = await client.get("/knowledge/search", headers=t["hb"], params={"q": f"{SECRET} retry decorator dependencies"})
    assert b.status_code == 200 and SECRET not in b.text and t["doc_id"] not in b.text
    a = await client.get("/knowledge/search", headers=t["ha"], params={"q": f"{SECRET} retry decorator dependencies"})
    assert SECRET in a.text
    assert (await client.post(f"/knowledge/sources/{t['doc_id']}/ingest", headers=t["hb"])).status_code == 404


@pytest.mark.asyncio
async def test_private_knowledge_isolation_qdrant(tenants):
    vec = get_embedding_service().embed([f"{SECRET} payments retry decorator"])[0]
    b = vector_store.search("knowledge_chunks", vec, TenantScope(organization_id=tenants["org_b"].id), limit=50)
    assert b, "B should still get the platform-public chunks"
    assert all(SECRET not in d.text and d.payload["visibility"] == "PLATFORM_PUBLIC" for d in b)
    a = vector_store.search("knowledge_chunks", vec, TenantScope(organization_id=tenants["org_a"].id), limit=50)
    assert any(SECRET in d.text for d in a)
    anon = vector_store.search("knowledge_chunks", vec, TenantScope(), limit=50)
    assert all(d.payload["visibility"] == "PLATFORM_PUBLIC" for d in anon)


@pytest.mark.asyncio
async def test_private_knowledge_never_reaches_llm_context_for_other_tenant(monkeypatch, tenants):
    fake = FakeLLM(monkeypatch, {"_Grounded": {"answer": "ok", "used_context": [1, 2]}})
    b = await grounded_answer(f"What does {SECRET} require?", TenantScope(organization_id=tenants["org_b"].id))
    # The question text contains SECRET, so check the private document's own
    # content never made it into the CONTEXT sent to the model.
    context_b = fake.all_text().split("QUESTION:")[0]
    assert SECRET not in context_b and "custom retry decorator" not in context_b
    assert all(r["document_id"] != tenants["doc_id"] for r in b.source_refs)
    fake.prompts.clear()
    a = await grounded_answer(f"What does {SECRET} require?", TenantScope(organization_id=tenants["org_a"].id))
    assert "custom retry decorator" in fake.all_text().split("QUESTION:")[0]
    assert any(r["document_id"] == tenants["doc_id"] for r in a.source_refs)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_rag_output_does_not_leak(client, tenants, monkeypatch):
    """Real Qwen, real retrieval. Spies on the exact prompt sent to the model."""
    from app.services.ai_gateway import gateway as gw
    from app.services.knowledge.service import retrieve

    sent: list[str] = []
    real_call = gw.AIGateway._call

    async def spy(self, pv, prompt, system, temperature, json_schema=None):
        sent.append((system or "") + "\n" + prompt)
        return await real_call(self, pv, prompt, system, temperature, json_schema)

    monkeypatch.setattr(gw.AIGateway, "_call", spy)
    question = "What must every FastAPI dependency in the payments service be wrapped in?"
    b_scope, a_scope = TenantScope(organization_id=tenants["org_b"].id), TenantScope(organization_id=tenants["org_a"].id)

    # 1 API retrieval, 2 reranked context, 3 prompt, 4 final output — all for Company B
    api_b = await client.get("/knowledge/search", headers=tenants["hb"], params={"q": question})
    assert PRIVATE_ONLY not in api_b.text
    vec = get_embedding_service().embed([question])[0]
    assert all(PRIVATE_ONLY not in d.text for d in vector_store.search("knowledge_chunks", vec, b_scope, limit=50))
    assert all(PRIVATE_ONLY not in d.text for d in retrieve(question, b_scope, top_k=30, top_n=5))
    b = await grounded_answer(question, b_scope)
    assert sent and all(PRIVATE_ONLY not in p for p in sent)
    assert PRIVATE_ONLY not in b.answer
    assert all(r["visibility"] == "PLATFORM_PUBLIC" for r in b.source_refs)

    # Company A retrieves its own private content through the same path
    sent.clear()
    assert PRIVATE_ONLY in (await client.get("/knowledge/search", headers=tenants["ha"], params={"q": question})).text
    a = await grounded_answer(question, a_scope)
    assert any(PRIVATE_ONLY in p for p in sent)
    assert any(r["document_id"] == tenants["doc_id"] for r in a.source_refs)
