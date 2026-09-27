"""Embedding + reranking via local sentence-transformers models.

Kept behind the AI Gateway package so callers never import
sentence-transformers directly.
"""

from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def _embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.EMBEDDING_MODEL)


@lru_cache
def _reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(settings.RERANKER_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    model = _embedder()
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def rerank(query: str, candidates: list[str], top_n: int = 5) -> list[tuple[int, float]]:
    """Returns (index_into_candidates, score) sorted best-first."""
    if not candidates:
        return []
    model = _reranker()
    pairs = [[query, c] for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [(idx, float(score)) for idx, score in ranked[:top_n]]
