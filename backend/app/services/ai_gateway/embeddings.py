"""BGE-M3 embeddings and BGE reranker, loaded once per process.

Both models are ~2.2GB. They load lazily on first use and are then reused
for the life of the process, guarded by a lock so concurrent requests in
the API process never trigger a second load. Celery runs with
`--pool=solo` (one process), so there's exactly one copy per worker; see
docs/LOCAL_SETUP.md for concurrency guidance.
"""

import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings

settings = get_settings()

EMBEDDING_DIM = 1024  # BAAI/bge-m3 dense dimension


def _model_kwargs() -> dict:
    """fp16 on Apple MPS / CUDA halves unified-memory use (measured on M4:
    BGE-M3 + reranker 5.34 GB fp32 -> 2.32 GB fp16) with effectively identical
    output (embedding cosine >= 0.9998, identical rerank order). CPU stays fp32."""
    import torch

    if settings.EMBEDDING_FP16 and (torch.backends.mps.is_available() or torch.cuda.is_available()):
        return {"torch_dtype": torch.float16}
    return {}


@dataclass
class RetrievedDocument:
    id: str
    text: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    rerank_score: float | None = None


class EmbeddingService:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, model_kwargs=_model_kwargs())
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(texts, normalize_embeddings=True, batch_size=16)
        return [v.tolist() for v in vectors]


class RerankerService:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.model_name, model_kwargs=_model_kwargs())
        return self._model

    def rerank(self, query: str, candidates: list[RetrievedDocument], top_n: int) -> list[RetrievedDocument]:
        """Scores only the already-retrieved candidates (e.g. Qdrant top-20..50)
        and returns the best `top_n`. Never called on a whole collection."""
        if not candidates:
            return []
        scores = self._load().predict([[query, c.text] for c in candidates])
        for c, s in zip(candidates, scores):
            c.rerank_score = float(s)
        return sorted(candidates, key=lambda c: c.rerank_score, reverse=True)[:top_n]


_embedder: EmbeddingService | None = None
_reranker: RerankerService | None = None
_init_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    global _embedder
    with _init_lock:
        if _embedder is None:
            _embedder = EmbeddingService(settings.EMBEDDING_MODEL)
    return _embedder


def get_reranker_service() -> RerankerService:
    global _reranker
    with _init_lock:
        if _reranker is None:
            _reranker = RerankerService(settings.RERANKER_MODEL)
    return _reranker


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedding_service().embed(texts)
