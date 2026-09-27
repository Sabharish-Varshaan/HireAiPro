"""Qdrant access with tenant scoping enforced *inside* the query.

Every search takes a `TenantScope`. It becomes a Qdrant filter that is
applied during retrieval, so a point another tenant owns is never a
candidate — we don't retrieve globally and discard in Python afterwards.
Postgres stays authoritative; Qdrant is semantic retrieval only.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import get_settings
from app.services.ai_gateway.embeddings import EMBEDDING_DIM, RetrievedDocument

settings = get_settings()

COLLECTIONS = ("knowledge_chunks", "questions", "skills", "jobs", "learning_resources")

# Only fields actually used in retrieval filters get an index.
INDEXED_FIELDS: dict[str, qm.PayloadSchemaType] = {
    "organization_id": qm.PayloadSchemaType.KEYWORD,
    "institution_id": qm.PayloadSchemaType.KEYWORD,
    "visibility": qm.PayloadSchemaType.KEYWORD,
    "skill_ids": qm.PayloadSchemaType.KEYWORD,
    "document_id": qm.PayloadSchemaType.KEYWORD,
    "source_type": qm.PayloadSchemaType.KEYWORD,
}


@dataclass(frozen=True)
class TenantScope:
    """Who is asking. `organization_id`/`institution_id` unlock that
    tenant's private content; platform-public content is always visible."""

    organization_id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None

    def to_filter(self) -> qm.Filter:
        allowed: list[qm.Condition] = [
            qm.FieldCondition(key="visibility", match=qm.MatchValue(value="PLATFORM_PUBLIC"))
        ]
        if self.organization_id:
            allowed.append(
                qm.Filter(
                    must=[
                        qm.FieldCondition(key="visibility", match=qm.MatchValue(value="COMPANY_PRIVATE")),
                        qm.FieldCondition(key="organization_id", match=qm.MatchValue(value=str(self.organization_id))),
                    ]
                )
            )
        if self.institution_id:
            allowed.append(
                qm.Filter(
                    must=[
                        qm.FieldCondition(key="visibility", match=qm.MatchValue(value="INSTITUTION_PRIVATE")),
                        qm.FieldCondition(key="institution_id", match=qm.MatchValue(value=str(self.institution_id))),
                    ]
                )
            )
        return qm.Filter(should=allowed)


def cname(logical: str) -> str:
    """Physical collection name (tests use a prefix so they never touch dev data)."""
    return f"{settings.QDRANT_COLLECTION_PREFIX}{logical}"


@lru_cache
def get_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)


_ensured: set[str] = set()


def ensure_collections() -> None:
    """Creates missing collections + payload indexes. Cached per process."""
    if settings.QDRANT_COLLECTION_PREFIX + "*" in _ensured:
        return
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    for logical in COLLECTIONS:
        name = cname(logical)
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=EMBEDDING_DIM, distance=qm.Distance.COSINE),
            )
        info = client.get_collection(name)
        have = set((info.payload_schema or {}).keys())
        for field_name, schema in INDEXED_FIELDS.items():
            if field_name not in have:
                client.create_payload_index(name, field_name=field_name, field_schema=schema, wait=True)
    _ensured.add(settings.QDRANT_COLLECTION_PREFIX + "*")


def upsert_points(collection: str, points: list[tuple[str, list[float], dict[str, Any]]]) -> None:
    """Point ids are deterministic (derived from Postgres ids), so repeated
    ingestion overwrites instead of duplicating."""
    if not points:
        return
    get_client().upsert(
        collection_name=cname(collection),
        points=[qm.PointStruct(id=pid, vector=vec, payload=payload) for pid, vec, payload in points],
        wait=True,
    )


def delete_by_document(collection: str, document_id: str) -> None:
    get_client().delete(
        collection_name=cname(collection),
        points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))])
        ),
        wait=True,
    )


def search(
    collection: str,
    vector: list[float],
    scope: TenantScope,
    limit: int = 30,
    skill_ids: list[str] | None = None,
    extra_must: list[qm.Condition] | None = None,
) -> list[RetrievedDocument]:
    """Tenant-scoped semantic search. `scope` is mandatory by signature."""
    tenant = scope.to_filter()
    must: list[qm.Condition] = [tenant]
    if skill_ids:
        must.append(qm.FieldCondition(key="skill_ids", match=qm.MatchAny(any=[str(s) for s in skill_ids])))
    if extra_must:
        must.extend(extra_must)
    result = get_client().query_points(
        collection_name=cname(collection),
        query=vector,
        query_filter=qm.Filter(must=must),
        limit=limit,
        with_payload=True,
    )
    return [
        RetrievedDocument(id=str(p.id), text=(p.payload or {}).get("text", ""), score=p.score, payload=p.payload or {})
        for p in result.points
    ]
