"""Knowledge Agent (PydanticAI).

Orchestrates ingestion of admin-approved sources for a skill:
get_skill → get_existing_sources → register_source → fetch_source →
extract_text → chunk_text → embed_chunks → store_chunks → mark_ready.

Every tool is a thin wrapper over app.services.knowledge.service. Bulky
intermediates (raw bytes, text, chunks, vectors) live in the typed deps so
the model only ever passes short ids between tools. The returned
KnowledgePackage is reconciled against what the tools actually persisted —
the model's own counts are never trusted.
"""

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ToolLog, build_agent, run_agent
from app.models.knowledge import KnowledgeSource, KnowledgeSourceStatus as KS
from app.services.knowledge import service as ks


class SourceSpec(BaseModel):
    title: str
    source_type: str  # INLINE_TEXT | LOCAL_FILE | APPROVED_URL
    source_uri: str
    raw_text: str | None = None


class KnowledgePackage(BaseModel):
    skill_id: uuid.UUID
    source_ids: list[uuid.UUID]
    sources_processed: int
    chunks_created: int
    status: str
    errors: list[str]


@dataclass
class KnowledgeDeps:
    db: AsyncSession
    skill_name: str
    sources: list[SourceSpec]
    visibility: str
    organization_id: uuid.UUID | None
    institution_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    log: ToolLog
    skill_id: uuid.UUID | None = None
    registered: dict[str, KnowledgeSource] = field(default_factory=dict)
    raw: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    text: dict[str, str] = field(default_factory=dict)
    chunks: dict[str, list[str]] = field(default_factory=dict)
    vectors: dict[str, list[list[float]]] = field(default_factory=dict)
    stored: dict[str, int] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


INSTRUCTIONS = """You ingest approved technical documentation into a knowledge base.
Steps, in order: call get_skill; call get_existing_sources; then for EACH
source index listed by get_existing_sources under 'to_register', call
register_source(index); then for each returned source_id call fetch_source,
extract_text, chunk_text, embed_chunks, store_chunks, mark_ready in that order.
If extract_text reports unchanged content, skip straight to mark_ready.
Pass only the ids the tools give you. When every source is READY or FAILED,
return the final KnowledgePackage."""

knowledge_agent = build_agent(KnowledgePackage, KnowledgeDeps, INSTRUCTIONS)


@knowledge_agent.tool
async def get_skill(ctx: RunContext[KnowledgeDeps]) -> dict:
    """Resolve the target skill to its canonical id."""
    d = ctx.deps
    skill = await ks.get_skill(d.db, d.skill_name)
    d.log.record("get_skill", skill=d.skill_name, found=bool(skill))
    if skill is None:
        return {"error": f"unknown skill {d.skill_name}"}
    d.skill_id = skill.id
    return {"skill_id": str(skill.id), "canonical_name": skill.canonical_name}


@knowledge_agent.tool
async def get_existing_sources(ctx: RunContext[KnowledgeDeps]) -> dict:
    """List sources already ingested for the skill and the pending sources to register."""
    d = ctx.deps
    existing = await ks.get_existing_sources(d.db, d.skill_id) if d.skill_id else []
    d.log.record("get_existing_sources", count=len(existing))
    return {
        "existing": [{"source_id": str(s.id), "uri": s.source_uri, "status": s.status} for s in existing],
        "to_register": [{"index": i, "title": s.title, "uri": s.source_uri} for i, s in enumerate(d.sources)],
    }


@knowledge_agent.tool
async def register_source(ctx: RunContext[KnowledgeDeps], index: int) -> dict:
    """Register pending source number `index` (idempotent per uri+tenant)."""
    d = ctx.deps
    spec = d.sources[index]
    src = await ks.register_source(
        d.db, title=spec.title, source_type=spec.source_type, source_uri=spec.source_uri,
        skill_ids=[d.skill_id], visibility=d.visibility, organization_id=d.organization_id,
        institution_id=d.institution_id, owner_user_id=d.owner_user_id, raw_text=spec.raw_text,
    )
    d.registered[str(src.id)] = src
    d.log.record("register_source", source_id=src.id, uri=spec.source_uri)
    return {"source_id": str(src.id), "status": src.status}


def _src(d: KnowledgeDeps, source_id: str) -> KnowledgeSource:
    if source_id not in d.registered:
        raise ValueError(f"unknown source_id {source_id}; call register_source first")
    return d.registered[source_id]


@knowledge_agent.tool
async def fetch_source(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Read the approved source's raw bytes (allowlisted hosts / local seeds only)."""
    d = ctx.deps
    src = _src(d, source_id)
    src.status = KS.PROCESSING
    try:
        d.raw[source_id] = await ks.fetch_source(src)
    except Exception as exc:  # noqa: BLE001
        await ks.mark_failed(d.db, src, str(exc))
        d.errors.append(f"{src.source_uri}: {exc}")
        d.log.record("fetch_source", source_id=source_id, ok=False)
        return {"error": str(exc)}
    d.log.record("fetch_source", source_id=source_id, bytes=len(d.raw[source_id][0]))
    return {"bytes": len(d.raw[source_id][0])}


@knowledge_agent.tool
async def extract_text(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Convert fetched bytes to clean text and report whether content changed."""
    d = ctx.deps
    raw, mime = d.raw[source_id]
    d.text[source_id] = ks.extract_text(raw, mime)
    src = _src(d, source_id)
    unchanged = src.content_hash == ks.content_hash(d.text[source_id]) and src.chunk_count > 0
    if unchanged:
        d.skipped.add(source_id)
    d.log.record("extract_text", source_id=source_id, chars=len(d.text[source_id]), unchanged=unchanged)
    return {"chars": len(d.text[source_id]), "unchanged": unchanged}


@knowledge_agent.tool
async def chunk_text(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Split extracted text into overlapping chunks."""
    d = ctx.deps
    d.chunks[source_id] = ks.chunk_text(d.text[source_id])
    d.log.record("chunk_text", source_id=source_id, chunks=len(d.chunks[source_id]))
    return {"chunks": len(d.chunks[source_id])}


@knowledge_agent.tool
async def embed_chunks(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Embed the chunks with BGE-M3."""
    d = ctx.deps
    d.vectors[source_id] = ks.embed_chunks(d.chunks[source_id])
    d.log.record("embed_chunks", source_id=source_id, vectors=len(d.vectors[source_id]))
    return {"vectors": len(d.vectors[source_id])}


@knowledge_agent.tool
async def store_chunks(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Persist chunks to Postgres and Qdrant (replacing older chunks of this source)."""
    d = ctx.deps
    d.stored[source_id] = await ks.store_chunks(d.db, _src(d, source_id), d.chunks[source_id], d.vectors[source_id])
    d.log.record("store_chunks", source_id=source_id, stored=d.stored[source_id])
    return {"stored": d.stored[source_id]}


@knowledge_agent.tool
async def mark_ready(ctx: RunContext[KnowledgeDeps], source_id: str) -> dict:
    """Mark the source READY once its chunks are stored (or its content was unchanged)."""
    d = ctx.deps
    src = _src(d, source_id)
    if source_id in d.skipped:
        src.status = KS.READY
    elif source_id in d.stored:
        await ks.mark_ready(d.db, src, ks.content_hash(d.text[source_id]), d.stored[source_id])
    else:
        return {"error": "store_chunks has not run for this source"}
    d.log.record("mark_ready", source_id=source_id)
    return {"status": src.status, "chunks": src.chunk_count}


def _reconcile(d: KnowledgeDeps) -> KnowledgePackage:
    srcs = list(d.registered.values())
    ready = [s for s in srcs if s.status == KS.READY]
    status = "READY" if srcs and len(ready) == len(srcs) else ("FAILED" if not ready else "PARTIAL")
    return KnowledgePackage(
        skill_id=d.skill_id or uuid.UUID(int=0),
        source_ids=[s.id for s in srcs],
        sources_processed=len(ready),
        chunks_created=sum(d.stored.values()),
        status=status,
        errors=d.errors,
    )


async def run_knowledge_agent(
    db: AsyncSession,
    *,
    skill_name: str,
    sources: list[SourceSpec],
    visibility: str = "PLATFORM_PUBLIC",
    organization_id: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    use_llm: bool = True,
) -> KnowledgePackage:
    log = ToolLog()
    deps = KnowledgeDeps(
        db=db, skill_name=skill_name, sources=sources, visibility=visibility,
        organization_id=organization_id, institution_id=institution_id,
        owner_user_id=owner_user_id, log=log,
    )

    async def llm() -> KnowledgePackage:
        await knowledge_agent.run(f"Ingest {len(sources)} approved source(s) for skill '{skill_name}'.", deps=deps)
        pkg = _reconcile(deps)
        if pkg.sources_processed < len(sources) and not deps.errors:
            raise RuntimeError("agent stopped before every source was READY")
        return pkg

    async def fallback() -> KnowledgePackage:
        skill = await ks.get_skill(db, skill_name)
        if skill is None:
            raise ValueError(f"unknown skill {skill_name}")
        deps.skill_id = skill.id
        log.record("fallback:get_skill", skill_id=skill.id)
        for spec in sources:
            src = await ks.register_source(
                db, title=spec.title, source_type=spec.source_type, source_uri=spec.source_uri,
                skill_ids=[skill.id], visibility=visibility, organization_id=organization_id,
                institution_id=institution_id, owner_user_id=owner_user_id, raw_text=spec.raw_text,
            )
            deps.registered[str(src.id)] = src
            try:
                result = await ks.ingest_source(db, src)
                deps.stored[str(src.id)] = result["chunks"] if not result["skipped"] else 0
                log.record("fallback:ingest_source", source_id=src.id, **result)
            except Exception as exc:  # noqa: BLE001
                deps.errors.append(f"{spec.source_uri}: {exc}")
        return _reconcile(deps)

    pkg = await run_agent(
        agent_type="knowledge_agent", task=f"ingest:{skill_name}", context_type="skill", context_id=None,
        tool_log=log, run_llm=llm if use_llm else _raise_disabled, fallback=fallback,
        required_tools={"get_skill", "register_source", "fetch_source", "mark_ready"},
    )
    await db.commit()
    return pkg


async def _raise_disabled():
    raise RuntimeError("LLM orchestration disabled for this call")
