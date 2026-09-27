"""Deterministic knowledge-ingestion and retrieval services.

The Knowledge Agent orchestrates these as tools; none of them call an LLM.
Ingestion is idempotent: sources are unique per (uri, tenant), chunk ids are
derived from (document_id, chunk_index), and unchanged content (same hash,
already READY) is skipped entirely.
"""

import datetime as dt
import hashlib
import html
import re
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import KnowledgeChunk, KnowledgeSource, KnowledgeSourceStatus as KS
from app.models.skills import Skill
from app.services.ai_gateway import vector_store
from app.services.ai_gateway.embeddings import RetrievedDocument, get_embedding_service, get_reranker_service
from app.services.ai_gateway.vector_store import TenantScope

settings = get_settings()

CHUNK_NAMESPACE = uuid.UUID("6f1c2a52-9b1e-4a57-9f2d-2f5b9c1e7a10")
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

# No autonomous crawling: only these official documentation hosts can be
# fetched, and only the exact URL an admin registered (links aren't followed).
APPROVED_HOSTS = {
    "fastapi.tiangolo.com",
    "docs.python.org",
    "www.postgresql.org",
    "docs.docker.com",
    "kubernetes.io",
    "react.dev",
    "developer.mozilla.org",
    "docs.pydantic.dev",
    "redis.io",
    "docs.sqlalchemy.org",
    "git-scm.com",
    "pandas.pydata.org",
    "numpy.org",
    "pytorch.org",
    "docs.celeryq.dev",
    "www.typescriptlang.org",
    "nodejs.org",
    "docs.djangoproject.com",
    "docs.aws.amazon.com",
}
ALLOWED_LOCAL_ROOT = Path(__file__).resolve().parents[3] / "seeds" / "knowledge"


class KnowledgeError(Exception):
    pass


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def get_skill(db: AsyncSession, skill_name_or_id: str) -> Skill | None:
    try:
        return await db.get(Skill, uuid.UUID(skill_name_or_id))
    except ValueError:
        return await db.scalar(select(Skill).where(Skill.canonical_name.ilike(skill_name_or_id)))


async def get_existing_sources(db: AsyncSession, skill_id: uuid.UUID) -> list[KnowledgeSource]:
    return list(
        (await db.scalars(select(KnowledgeSource).where(KnowledgeSource.skill_ids.any(str(skill_id))))).all()
    )


async def register_source(
    db: AsyncSession,
    *,
    title: str,
    source_type: str,
    source_uri: str,
    skill_ids: list[uuid.UUID],
    visibility: str,
    organization_id: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    raw_text: str | None = None,
) -> KnowledgeSource:
    if visibility == "COMPANY_PRIVATE" and not organization_id:
        raise KnowledgeError("COMPANY_PRIVATE sources require organization_id")
    if visibility == "INSTITUTION_PRIVATE" and not institution_id:
        raise KnowledgeError("INSTITUTION_PRIVATE sources require institution_id")
    if source_type == "APPROVED_URL":
        host = urlparse(source_uri).hostname or ""
        if host not in APPROVED_HOSTS:
            raise KnowledgeError(f"Host '{host}' is not on the approved documentation allowlist")

    existing = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.source_uri == source_uri,
            KnowledgeSource.organization_id.is_(None) if organization_id is None else KnowledgeSource.organization_id == organization_id,
            KnowledgeSource.institution_id.is_(None) if institution_id is None else KnowledgeSource.institution_id == institution_id,
        )
    )
    if existing:
        merged = sorted(set(existing.skill_ids) | {str(s) for s in skill_ids})
        existing.skill_ids = merged
        if raw_text is not None and raw_text != existing.raw_text:
            existing.raw_text = raw_text
        await db.flush()
        return existing

    src = KnowledgeSource(
        title=title,
        source_type=source_type,
        source_uri=source_uri,
        organization_id=organization_id,
        institution_id=institution_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
        skill_ids=[str(s) for s in skill_ids],
        status=KS.REGISTERED,
        raw_text=raw_text,
    )
    db.add(src)
    await db.flush()
    return src


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "svg", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in {"p", "li", "h1", "h2", "h3", "h4", "pre", "tr", "br", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


async def fetch_source(src: KnowledgeSource) -> tuple[bytes, str]:
    """Returns (raw bytes, mime hint)."""
    if src.source_type == "INLINE_TEXT":
        return (src.raw_text or "").encode("utf-8"), "text/plain"
    if src.source_type == "LOCAL_FILE":
        path = (ALLOWED_LOCAL_ROOT / src.source_uri).resolve()
        if ALLOWED_LOCAL_ROOT not in path.parents:
            raise KnowledgeError("Local knowledge files must live under seeds/knowledge/")
        return path.read_bytes(), "text/html" if path.suffix in {".html", ".htm"} else "text/plain"
    if src.source_type == "APPROVED_URL":
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(src.source_uri, headers={"User-Agent": "HireAiPro-KnowledgeAgent/1.0"})
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "text/html")
    raise KnowledgeError(f"Unsupported source_type {src.source_type}")


def extract_text(raw: bytes, mime: str) -> str:
    if "html" in mime:
        parser = _TextExtractor()
        parser.feed(raw.decode("utf-8", errors="ignore"))
        text = html.unescape("".join(parser.parts))
    elif "pdf" in mime:
        from app.services.documents.extraction import extract_text as extract_doc

        text = extract_doc(raw, "application/pdf", "doc.pdf")
    else:
        text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware packing into ~`size`-char chunks with a character
    overlap carried from the previous chunk's tail."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:
            head, para = para[:size], para[size - overlap:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{para}" if tail else para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= 40]


def chunk_id(document_id: uuid.UUID, index: int) -> uuid.UUID:
    return uuid.uuid5(CHUNK_NAMESPACE, f"{document_id}:{index}")


def embed_chunks(chunks: list[str]) -> list[list[float]]:
    return get_embedding_service().embed(chunks)


async def store_chunks(
    db: AsyncSession, src: KnowledgeSource, chunks: list[str], vectors: list[list[float]]
) -> int:
    """Replaces this document's chunks in both Postgres and Qdrant."""
    vector_store.ensure_collections()
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == src.id))
    vector_store.delete_by_document("knowledge_chunks", str(src.id))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    points = []
    for idx, (text, vec) in enumerate(zip(chunks, vectors)):
        cid = chunk_id(src.id, idx)
        chash = content_hash(text)
        db.add(
            KnowledgeChunk(
                id=cid, document_id=src.id, chunk_index=idx, text=text, content_hash=chash,
                embedding_model=settings.EMBEDDING_MODEL,
            )
        )
        payload = {
            "document_id": str(src.id),
            "chunk_id": str(cid),
            "chunk_index": idx,
            "text": text,
            "title": src.title,
            "source_uri": src.source_uri,
            "source_type": src.source_type,
            "skill_ids": list(src.skill_ids),
            "visibility": src.visibility,
            "content_hash": chash,
            "embedding_model": settings.EMBEDDING_MODEL,
            "created_at": now,
        }
        if src.organization_id:
            payload["organization_id"] = str(src.organization_id)
        if src.institution_id:
            payload["institution_id"] = str(src.institution_id)
        if src.owner_user_id:
            payload["owner_id"] = str(src.owner_user_id)
        points.append((str(cid), vec, payload))
    vector_store.upsert_points("knowledge_chunks", points)
    await db.flush()
    return len(points)


async def mark_ready(db: AsyncSession, src: KnowledgeSource, text_hash: str, chunk_count: int) -> None:
    src.status = KS.READY
    src.content_hash = text_hash
    src.chunk_count = chunk_count
    src.document_version = (src.document_version or 0) + 1
    src.embedding_model = settings.EMBEDDING_MODEL
    src.last_ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    src.error = None
    await db.flush()


async def mark_failed(db: AsyncSession, src: KnowledgeSource, error: str) -> None:
    src.status = KS.FAILED
    src.error = error[:2000]
    await db.flush()


async def ingest_source(db: AsyncSession, src: KnowledgeSource) -> dict:
    """The full deterministic pipeline in one call. Used as the agent's
    fallback path and by retries; the agent itself calls the steps one by one."""
    src.status = KS.PROCESSING
    await db.flush()
    try:
        raw, mime = await fetch_source(src)
        text = extract_text(raw, mime)
        text_hash = content_hash(text)
        if src.content_hash == text_hash and src.chunk_count > 0:
            src.status = KS.READY
            await db.flush()
            return {"skipped": True, "chunks": src.chunk_count}
        chunks = chunk_text(text)
        if not chunks:
            raise KnowledgeError("Source produced no usable text")
        count = await store_chunks(db, src, chunks, embed_chunks(chunks))
        await mark_ready(db, src, text_hash, count)
        return {"skipped": False, "chunks": count}
    except Exception as exc:  # noqa: BLE001
        await mark_failed(db, src, str(exc))
        raise


def retrieve(
    query: str,
    scope: TenantScope,
    skill_ids: list[uuid.UUID] | None = None,
    top_k: int = 30,
    top_n: int = 5,
) -> list[RetrievedDocument]:
    """query → BGE-M3 → tenant-filtered Qdrant top-K → BGE reranker → top-N."""
    vector_store.ensure_collections()
    qvec = get_embedding_service().embed([query])[0]
    candidates = vector_store.search(
        "knowledge_chunks", qvec, scope, limit=top_k,
        skill_ids=[str(s) for s in skill_ids] if skill_ids else None,
    )
    return get_reranker_service().rerank(query, candidates, top_n)


def to_source_refs(docs: list[RetrievedDocument]) -> list[dict]:
    return [
        {
            "document_id": d.payload.get("document_id"),
            "chunk_id": d.payload.get("chunk_id"),
            "title": d.payload.get("title"),
            "source_uri": d.payload.get("source_uri"),
            "visibility": d.payload.get("visibility"),
            "rerank_score": round(d.rerank_score, 4) if d.rerank_score is not None else None,
        }
        for d in docs
    ]
