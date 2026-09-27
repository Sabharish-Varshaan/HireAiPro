"""RAG: tenant-scoped retrieve → rerank → Qwen, with provenance.

Provenance is never taken from the LLM's say-so. The model is shown numbered
context blocks and returns the numbers it used; those are mapped back to
the real (document_id, chunk_id) of the retrieved chunks. Out-of-range
numbers are dropped, so a model can't cite a chunk it wasn't given.
"""

import uuid

from pydantic import BaseModel, Field

from app.services.ai_gateway.gateway import get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.knowledge.service import retrieve, to_source_refs


class _Grounded(BaseModel):
    answer: str
    used_context: list[int] = Field(default_factory=list)


class GroundedAnswer(BaseModel):
    answer: str
    source_refs: list[dict]
    retrieved: int


def format_context(docs) -> str:
    return "\n\n".join(f"[{i + 1}] ({d.payload.get('title')})\n{d.text}" for i, d in enumerate(docs))


def select_refs(docs, used: list[int]) -> list[dict]:
    valid = sorted({i for i in used if 1 <= i <= len(docs)})
    chosen = [docs[i - 1] for i in valid] or docs
    return to_source_refs(chosen)


async def grounded_answer(
    question: str, scope: TenantScope, skill_ids: list[uuid.UUID] | None = None, top_n: int = 4
) -> GroundedAnswer:
    docs = retrieve(question, scope, skill_ids=skill_ids, top_k=30, top_n=top_n)
    if not docs:
        return GroundedAnswer(answer="No approved knowledge is available for this question.", source_refs=[], retrieved=0)
    out = await get_ai_gateway().generate_structured(
        f"CONTEXT:\n{format_context(docs)}\n\nQUESTION: {question}",
        _Grounded,
        system=(
            "Answer ONLY from the numbered CONTEXT blocks. If the context does not contain the answer, "
            "say so. List the block numbers you used in used_context."
        ),
        task_type="rag_answer",
    )
    return GroundedAnswer(answer=out.answer, source_refs=select_refs(docs, out.used_context), retrieved=len(docs))
