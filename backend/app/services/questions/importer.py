"""Company question-bank import pipeline, shared by manual creation, paste,
CSV and JSON upload:

    parse → skill normalization → difficulty estimation (if missing)
          → rubric/expected-concept completion (if missing, TECHNICAL only)
          → validation → COMPANY_PRIVATE (or PLATFORM for platform admins)

CSV columns (header row required):
    question_text, question_type, skill, difficulty, options, correct_option,
    expected_concepts, test_cases
  - options / expected_concepts: "|"-separated
  - correct_option: 0-based index
  - test_cases: JSON list of {"input","expected_output"}

JSON: a list of objects with the same keys (options/expected_concepts as
lists, test_cases as a list).
"""

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import QuestionSourceType, QuestionStatus as QS, QuestionType, Visibility
from app.models.questions import Question
from app.models.skills import Skill
from app.services.ai_gateway.gateway import AIGatewayError, get_ai_gateway
from app.services.ai_gateway.vector_store import TenantScope
from app.services.questions.validator import content_hash, index_question, validate_semantics, validate_structure
from app.services.skills.normalizer import normalize_skill_name

HARD_HINTS = re.compile(r"\b(design|architect|trade-?offs?|optimi[sz]e|scale|distributed|concurren)", re.I)
EASY_HINTS = re.compile(r"^\s*(what is|what are|define|which|name|list)\b", re.I)


class ImportRow(BaseModel):
    question_text: str
    question_type: QuestionType = QuestionType.TECHNICAL
    skill: str
    difficulty: str | None = None
    options: list[str] | None = None
    correct_option: int | None = None
    expected_concepts: list[str] | None = None
    test_cases: list[dict] | None = None
    rubric: dict | None = None


@dataclass
class ImportReport:
    created: list[Question] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "created": len(self.created),
            "validated": sum(1 for q in self.created if q.status == QS.VALIDATED),
            "draft": sum(1 for q in self.created if q.status == QS.DRAFT),
            "duplicates": self.duplicates,
            "errors": self.errors,
            "question_ids": [str(q.id) for q in self.created],
        }


class _RubricFill(BaseModel):
    expected_concepts: list[str] = Field(min_length=2)
    rubric_criteria: list[str] = Field(min_length=2)


def estimate_difficulty(qtype: QuestionType, text: str) -> str:
    """Deterministic heuristic, used only when the uploader gave none."""
    if EASY_HINTS.search(text) and qtype == QuestionType.MCQ:
        return "easy"
    if HARD_HINTS.search(text):
        return "hard"
    if EASY_HINTS.search(text):
        return "easy"
    return "medium"


def parse_csv(raw: bytes) -> list[dict]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    rows = []
    for r in reader:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        rows.append({
            "question_text": r.get("question_text", ""),
            "question_type": (r.get("question_type") or "TECHNICAL").upper(),
            "skill": r.get("skill", ""),
            "difficulty": r.get("difficulty") or None,
            "options": [o.strip() for o in r["options"].split("|")] if r.get("options") else None,
            "correct_option": int(r["correct_option"]) if r.get("correct_option") not in (None, "") else None,
            "expected_concepts": [c.strip() for c in r["expected_concepts"].split("|")] if r.get("expected_concepts") else None,
            "test_cases": json.loads(r["test_cases"]) if r.get("test_cases") else None,
        })
    return rows


def parse_json(raw: bytes) -> list[dict]:
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict):
        data = data.get("questions", [])
    return data


def parse_paste(text: str, skill: str, question_type: QuestionType) -> list[dict]:
    """One question per blank-line-separated block. Leading numbering like
    '1.' or 'Q1:' is stripped."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [
        {"question_text": re.sub(r"^\s*(q?\d+[.):]|q:)\s*", "", b, flags=re.I), "question_type": question_type.value, "skill": skill}
        for b in blocks
    ]


async def import_rows(
    db: AsyncSession,
    raw_rows: list[dict],
    *,
    organization_id: uuid.UUID | None,
    created_by: uuid.UUID,
    platform: bool = False,
) -> ImportReport:
    report = ImportReport()
    scope = TenantScope(organization_id=organization_id)
    for i, raw in enumerate(raw_rows):
        try:
            row = ImportRow.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            report.errors.append({"row": i, "error": f"schema: {exc}"[:300]})
            continue
        skill_id, _ = await normalize_skill_name(db, row.skill)
        if skill_id is None:
            report.errors.append({"row": i, "error": f"unknown skill '{row.skill}' (not in the canonical taxonomy)"})
            continue
        skill = await db.get(Skill, skill_id)
        difficulty = (row.difficulty or estimate_difficulty(row.question_type, row.question_text)).lower()

        expected, rubric = row.expected_concepts, row.rubric
        if row.question_type == QuestionType.TECHNICAL and (not expected or not rubric):
            try:
                fill = await get_ai_gateway().generate_structured(
                    f"For this interview question about '{skill.canonical_name}', list 3-5 expected concepts a "
                    f"strong answer covers and 3-4 grading criteria.\n\nQUESTION: {row.question_text}",
                    _RubricFill, task_type="rubric_completion",
                )
                expected = expected or fill.expected_concepts
                rubric = rubric or {"criteria": fill.rubric_criteria, "version": "rubric_v1", "generated": True}
            except AIGatewayError as exc:
                report.errors.append({"row": i, "error": f"rubric completion failed, saved as DRAFT: {exc}"[:300]})

        result = validate_structure(
            row.question_type, row.question_text, difficulty, expected, rubric, row.options, row.correct_option, row.test_cases
        )
        result = validate_semantics(result, row.question_text, skill.canonical_name, skill_id, scope)
        if result.duplicate_of:
            report.duplicates.append({"row": i, "duplicate_of": result.duplicate_of})
            continue

        q = Question(
            question_text=row.question_text.strip(), question_type=row.question_type, skill_id=skill_id,
            difficulty=difficulty, options=row.options, correct_option_index=row.correct_option,
            expected_concepts=expected, rubric=rubric, test_cases=row.test_cases,
            source_type=QuestionSourceType.PLATFORM if platform else QuestionSourceType.COMPANY_PRIVATE,
            organization_id=None if platform else organization_id,
            visibility=Visibility.PLATFORM_PUBLIC if platform else Visibility.COMPANY_PRIVATE,
            status=QS.VALIDATED if result.ok else QS.DRAFT,
            content_hash=content_hash(row.question_text), validation_report=result.report(),
            created_by_user_id=created_by,
        )
        db.add(q)
        await db.flush()
        index_question(q, result.embedding)
        report.created.append(q)
    return report
