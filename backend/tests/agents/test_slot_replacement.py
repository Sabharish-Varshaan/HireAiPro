"""Bounded replacement generation: a rejected candidate triggers a replacement
that is told why; after the attempt limit the slot is reported uncovered."""
import uuid
from types import SimpleNamespace

import pytest

from app.agents import assessment_agent as AA
from app.models.enums import QuestionStatus as QS, QuestionType
from app.services.assessments.blueprint import SkillAllocation


class _Gen:
    """Scripted stand-in for gen.generate_missing_question (records every call)."""

    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    async def __call__(self, db, **kw):
        self.calls.append(kw)
        ok, reason = self.outcomes.pop(0)
        return SimpleNamespace(id=uuid.uuid4(), status=QS.VALIDATED if ok else QS.DRAFT, source_refs=[],
                               question_text=f"q{len(self.calls)}",
                               validation_report={"reasons": [] if ok else [reason]})


def _deps(monkeypatch, outcomes, need=1, attempts=3):
    g = _Gen(outcomes)
    monkeypatch.setattr(AA.gen, "generate_missing_question", g)
    monkeypatch.setattr(AA.gen, "content_hash", lambda t: "h:" + t)
    monkeypatch.setattr(AA, "get_settings", lambda: SimpleNamespace(ASSESSMENT_SLOT_GENERATION_ATTEMPTS=attempts))

    async def _noaudit(*a, **k):
        return None
    monkeypatch.setattr(AA, "audit", _noaudit)
    alloc = SkillAllocation(skill_id=uuid.uuid4(), skill_name="Algorithms", weight=1.0, mcq_count=0, technical_count=0, coding_count=need)
    w = AA.SkillWork(alloc=alloc, need={QuestionType.CODING: need}, company_searched=True, platform_searched=True)
    d = SimpleNamespace(db=None, job=SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()), actor_user_id=None, work=[w])
    return d, w, g


@pytest.mark.asyncio
async def test_rejected_candidate_is_replaced_and_told_why(monkeypatch):
    d, w, g = _deps(monkeypatch, [(False, "independent reference solution disagrees with the expected output (test 1)"), (True, "")])
    await AA._generate_for(d, 0)
    assert w.remaining(QuestionType.CODING) == 0 and len(g.calls) == 2
    assert g.calls[0]["avoid"] == [] and "reference solution disagrees" in g.calls[1]["avoid"][0]
    assert g.calls[1]["rejected_hashes"] == {"h:q1"} and g.calls[0]["slot"] != g.calls[1]["slot"]


@pytest.mark.asyncio
async def test_second_replacement_can_cover_the_slot(monkeypatch):
    d, w, g = _deps(monkeypatch, [(False, "near-duplicate"), (False, "weak alignment"), (True, "")])
    await AA._generate_for(d, 0)
    assert w.remaining(QuestionType.CODING) == 0 and len(g.calls) == 3 and w.generation_attempts == 3


@pytest.mark.asyncio
async def test_all_attempts_invalid_leaves_slot_uncovered_and_bounded(monkeypatch):
    d, w, g = _deps(monkeypatch, [(False, "bad expected output")] * 3, need=2)
    await AA._generate_for(d, 0)
    assert len(g.calls) == 3                     # bounded: never more than the attempt limit per slot
    assert w.remaining(QuestionType.CODING) == 2  # honestly uncovered
    assert w.rejections[QuestionType.CODING] == ["bad expected output"] * 3
