"""BGE-M3 embeddings and BGE reranker.

They load lazily on first use, guarded by a lock so concurrent requests never
trigger a second load, and are released again after MODEL_IDLE_UNLOAD_SECONDS
without use. Both the API and the Celery worker need them, and keeping both
copies resident for the life of each process measured ~4.5 GB footprint per
process on an M4 (2026-09-29), enough to push a 16 GB laptop into swap and
process kills. A reload costs a few seconds; the weights, and therefore every
vector and rerank score, are identical.
"""

import gc
import logging
import threading
import time
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


logger = logging.getLogger(__name__)


class _IdleReleasedModel:
    """Loads on demand, runs inference under the lock (so a release can never
    pull the weights out from under a running call) and frees the model after
    `idle_seconds` without use. idle_seconds <= 0 keeps it resident."""

    def __init__(self, model_name: str, idle_seconds: int | None = None) -> None:
        self.model_name = model_name
        self.idle_seconds = settings.MODEL_IDLE_UNLOAD_SECONDS if idle_seconds is None else idle_seconds
        self._model = None
        self._last_used = 0.0
        self._lock = threading.Lock()
        self._janitor: threading.Thread | None = None

    def _build(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def _run(self, fn):
        with self._lock:
            if self._model is None:
                self._model = self._build()
                self._start_janitor()
            self._last_used = time.monotonic()
            try:
                return fn(self._model)
            finally:
                self._last_used = time.monotonic()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def release_if_idle(self, now: float | None = None) -> bool:
        with self._lock:
            if self._model is None or self.idle_seconds <= 0:
                return False
            if (now if now is not None else time.monotonic()) - self._last_used < self.idle_seconds:
                return False
            self._model = None
        gc.collect()
        _empty_accelerator_cache()
        logger.info("released idle model %s", self.model_name)
        return True

    def _start_janitor(self) -> None:
        if self.idle_seconds <= 0 or (self._janitor and self._janitor.is_alive()):
            return

        def loop() -> None:
            while True:
                time.sleep(min(30, self.idle_seconds))
                self.release_if_idle()

        self._janitor = threading.Thread(target=loop, name=f"idle-release:{self.model_name}", daemon=True)
        self._janitor.start()


def _cached_first(build):
    """Reloads after an idle release happen often, so load from the local HF cache
    without network round-trips; only a model that was never downloaded goes online."""
    try:
        return build(local_files_only=True)
    except OSError:
        return build()


def _empty_accelerator_cache() -> None:
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        logger.warning("could not empty accelerator cache", exc_info=True)


class EmbeddingService(_IdleReleasedModel):
    def _build(self):
        from sentence_transformers import SentenceTransformer

        return _cached_first(lambda **kw: SentenceTransformer(self.model_name, model_kwargs=_model_kwargs(), **kw))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._run(lambda m: m.encode(texts, normalize_embeddings=True, batch_size=16))
        return [v.tolist() for v in vectors]


class RerankerService(_IdleReleasedModel):
    def _build(self):
        from sentence_transformers import CrossEncoder

        return _cached_first(lambda **kw: CrossEncoder(self.model_name, model_kwargs=_model_kwargs(), **kw))

    def rerank(self, query: str, candidates: list[RetrievedDocument], top_n: int) -> list[RetrievedDocument]:
        """Scores only the already-retrieved candidates (e.g. Qdrant top-20..50)
        and returns the best `top_n`. Never called on a whole collection."""
        if not candidates:
            return []
        scores = self._run(lambda m: m.predict([[query, c.text] for c in candidates]))
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


def warm_models() -> dict:
    """Infrastructure warm-up for demos: one tiny embedding and one tiny rerank in
    *this* process (models are per-process). No business data is read or written;
    idle release still applies afterwards."""
    t0 = time.monotonic()
    embed(["warm-up"])
    t1 = time.monotonic()
    get_reranker_service().rerank("warm-up", [RetrievedDocument(id="w", text="warm-up", score=0.0)], top_n=1)
    return {"embedder_s": round(t1 - t0, 2), "reranker_s": round(time.monotonic() - t1, 2),
            "idle_unload_seconds": settings.MODEL_IDLE_UNLOAD_SECONDS}
