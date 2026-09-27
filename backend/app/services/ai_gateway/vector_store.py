from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import get_settings

settings = get_settings()

COLLECTIONS = {
    "knowledge_chunks": 1024,
    "questions": 1024,
    "skills": 1024,
    "jobs": 1024,
    "learning_resources": 1024,
}


@lru_cache
def get_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)


def ensure_collections() -> None:
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    for name, dim in COLLECTIONS.items():
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
            )


def upsert(collection: str, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
    client = get_client()
    client.upsert(
        collection_name=collection,
        points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)],
    )


def search(
    collection: str,
    vector: list[float],
    tenant_filter: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[Any]:
    """Semantic search with mandatory tenant filtering.

    tenant_filter example: {"visibility": "PLATFORM_PUBLIC"} or
    {"organization_id": "<uuid>"} — callers MUST pass tenant scoping so a
    private payload never leaks across organizations/institutions.
    """
    client = get_client()
    qfilter = None
    if tenant_filter:
        must = [
            qmodels.FieldCondition(key=k, match=qmodels.MatchValue(value=v))
            for k, v in tenant_filter.items()
        ]
        qfilter = qmodels.Filter(must=must)
    return client.search(
        collection_name=collection, query_vector=vector, query_filter=qfilter, limit=limit
    )
