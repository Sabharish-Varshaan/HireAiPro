"""Knowledge Agent: turns an admin-approved text source into embedded,
retrievable chunks for a skill. No autonomous crawling — the source text is
always supplied by an admin/recruiter action (pasted doc, uploaded file, or
a curated official-docs excerpt), never fetched from an arbitrary URL the
agent picks itself.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProcessingStatus, Visibility
from app.models.misc import AgentRun
from app.services.ai_gateway.embeddings import embed
from app.services.ai_gateway.vector_store import ensure_collections, upsert

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


@dataclass
class KnowledgePackage:
    skill_id: uuid.UUID
    source_id: str
    documents_processed: int
    chunks_created: int
    status: str


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start <= 0:
            break
    return [c.strip() for c in chunks if c.strip()]


async def ingest_knowledge_source(
    db: AsyncSession,
    skill_id: uuid.UUID,
    source_name: str,
    text: str,
    visibility: Visibility = Visibility.PLATFORM_PUBLIC,
    organization_id: uuid.UUID | None = None,
) -> KnowledgePackage:
    run = AgentRun(agent_type="knowledge_agent", task=f"ingest:{source_name}", status=ProcessingStatus.RUNNING)
    db.add(run)
    await db.flush()

    source_id = str(uuid.uuid4())
    try:
        ensure_collections()
        chunks = chunk_text(text)
        if chunks:
            vectors = embed(chunks)
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
                payload = {
                    "skill_id": str(skill_id),
                    "source_id": source_id,
                    "source_name": source_name,
                    "chunk_index": idx,
                    "text": chunk,
                    "visibility": visibility.value,
                }
                if organization_id:
                    payload["organization_id"] = str(organization_id)
                upsert("knowledge_chunks", f"{source_id}-{idx}", vector, payload)

        run.status = ProcessingStatus.COMPLETED
        run.tool_calls = [{"tool": "chunk_source", "chunks": len(chunks)}, {"tool": "embed_chunks"}, {"tool": "store_chunks"}]
        run.ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        await db.commit()
        return KnowledgePackage(
            skill_id=skill_id, source_id=source_id, documents_processed=1, chunks_created=len(chunks), status="READY"
        )
    except Exception as exc:  # noqa: BLE001
        run.status = ProcessingStatus.FAILED
        run.error = str(exc)
        run.ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        await db.commit()
        raise
