"""Deterministic question validation + embedding-based duplicate detection.

No LLM judges validity. Each check is a plain rule whose result lands in
`questions.validation_report`, so an admin can see exactly why a question
was held back in DRAFT/REJECTED.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field

import numpy as np
from qdrant_client.http import models as qm

from app.models.enums import QuestionType
from app.services.ai_gateway import vector_store
from app.services.ai_gateway.embeddings import get_embedding_service, get_reranker_service
from app.services.ai_gateway.vector_store import TenantScope

DIFFICULTIES = {"easy", "medium", "hard"}
DUPLICATE_THRESHOLD = 0.92  # cosine similarity on normalized BGE-M3 vectors
SKILL_ALIGNMENT_THRESHOLD = 0.35
GROUNDING_THRESHOLD = 0.3  # reranker relevance of question vs. its cited context
AMBIGUOUS_MCQ = re.compile(r"\b(all|none) of the above\b", re.I)


@dataclass
class ValidationResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    embedding: list[float] | None = None

    def report(self) -> dict:
        return {"ok": self.ok, "checks": self.checks, "reasons": self.reasons, "duplicate_of": self.duplicate_of}


def content_hash(question_text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", question_text.strip().lower()).encode()).hexdigest()


def _cos(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a), np.asarray(b)))


def validate_structure(
    question_type: QuestionType,
    question_text: str,
    difficulty: str,
    expected_concepts: list[str] | None,
    rubric: dict | None,
    options: list | None,
    correct_option_index: int | None,
    test_cases: list | None,
) -> ValidationResult:
    r = ValidationResult(ok=True)

    def check(name: str, passed: bool, reason: str) -> None:
        r.checks[name] = passed
        if not passed:
            r.reasons.append(reason)

    text = (question_text or "").strip()
    check("schema_text", len(text) >= 15, "question text too short")
    check("difficulty", difficulty in DIFFICULTIES, f"difficulty must be one of {sorted(DIFFICULTIES)}")
    check("answerability", len(text) <= 1500 and not text.endswith("..."), "question is truncated or too long")

    if question_type == QuestionType.MCQ:
        opts = [str(o).strip() for o in (options or [])]
        check("mcq_options", len(opts) >= 3, "MCQ requires at least 3 options")
        check("mcq_distinct", len({o.lower() for o in opts}) == len(opts), "MCQ options must be distinct")
        check(
            "mcq_answer_key",
            correct_option_index is not None and 0 <= correct_option_index < len(opts),
            "MCQ correct_option_index out of range",
        )
        check("mcq_unambiguous", not any(AMBIGUOUS_MCQ.search(o) for o in opts), "'all/none of the above' is ambiguous")
    elif question_type == QuestionType.TECHNICAL:
        check("expected_concepts", bool(expected_concepts) and len(expected_concepts) >= 2, "needs >=2 expected concepts")
        check("rubric", bool(rubric) and bool(rubric.get("criteria")), "technical question needs a rubric")
    elif question_type == QuestionType.CODING:
        tcs = test_cases or []
        check("test_cases", len(tcs) >= 2, "coding question needs >=2 test cases")
        check(
            "test_case_shape",
            all(isinstance(t, dict) and "input" in t and "expected_output" in t for t in tcs),
            "each test case needs input and expected_output",
        )
    r.ok = all(r.checks.values())
    return r


def validate_semantics(
    r: ValidationResult,
    question_text: str,
    skill_label: str,
    skill_id: uuid.UUID,
    scope: TenantScope,
    context_texts: list[str] | None = None,
) -> ValidationResult:
    """Skill alignment, grounding and duplicate checks (embedding-based)."""
    embedder = get_embedding_service()
    q_vec, s_vec = embedder.embed([question_text, skill_label])
    r.embedding = q_vec

    align = _cos(q_vec, s_vec)
    r.checks["skill_alignment"] = align >= SKILL_ALIGNMENT_THRESHOLD
    if not r.checks["skill_alignment"]:
        r.reasons.append(f"weak alignment with skill '{skill_label}' ({align:.2f})")

    if context_texts:
        best = max(get_reranker_service()._run(lambda m: m.predict([[question_text, c] for c in context_texts])))
        grounded = float(best) >= GROUNDING_THRESHOLD
        r.checks["grounding"] = grounded
        if not grounded:
            r.reasons.append(f"question not supported by its cited context ({float(best):.2f})")

    vector_store.ensure_collections()
    # Tenant-scoped but NOT skill-scoped: the same problem reworded under a sibling
    # skill (e.g. Data Structures vs Algorithms) is still a duplicate. Measured
    # 2026-09-29: such a pair scored 0.969; a genuinely different problem 0.826.
    near = vector_store.search("questions", q_vec, scope, limit=5, extra_must=None)
    dup = next((p for p in near if p.score >= DUPLICATE_THRESHOLD and p.payload.get("status") != "REJECTED"), None)
    r.checks["not_duplicate"] = dup is None
    if dup:
        r.duplicate_of = dup.payload.get("question_id")
        r.reasons.append(f"near-duplicate of question {r.duplicate_of} (similarity {dup.score:.3f})")

    r.ok = all(r.checks.values())
    return r


def index_question(question, embedding: list[float] | None = None) -> None:
    """Upsert a question into the tenant-scoped Qdrant `questions` collection.
    Point id == question id, so re-indexing overwrites."""
    vector_store.ensure_collections()
    vec = embedding or get_embedding_service().embed([question.question_text])[0]
    payload = {
        "question_id": str(question.id),
        "text": question.question_text,
        "skill_ids": [str(question.skill_id)],
        "visibility": str(question.visibility.value if hasattr(question.visibility, "value") else question.visibility),
        "status": str(question.status.value if hasattr(question.status, "value") else question.status),
        "question_type": str(question.question_type.value if hasattr(question.question_type, "value") else question.question_type),
        "source_type": str(question.source_type.value if hasattr(question.source_type, "value") else question.source_type),
    }
    if question.organization_id:
        payload["organization_id"] = str(question.organization_id)
    vector_store.upsert_points("questions", [(str(question.id), vec, payload)])


def remove_question_from_index(question_id: uuid.UUID) -> None:
    vector_store.get_client().delete(
        collection_name=vector_store.cname("questions"), points_selector=qm.PointIdsList(points=[str(question_id)]), wait=True
    )
