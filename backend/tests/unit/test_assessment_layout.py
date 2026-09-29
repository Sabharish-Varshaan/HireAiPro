"""Question/option randomization is real (not per-section no-op), persisted, and legacy layouts still read."""
import uuid
from types import SimpleNamespace

from app.services.assessments import versioning as ver


def _fz(n_sections=12, per=1):
    fz = ver.Frozen()
    for s in range(n_sections):
        ids = []
        for k in range(per):
            aq = uuid.uuid4()
            fz.by_aq[aq] = ver.FrozenQ(aq_id=aq, section_id=uuid.uuid4(), order_index=k, points=1.0, id=uuid.uuid4(), question_text="q" * 20,
                                       question_type="MCQ", skill_id=uuid.uuid4(), difficulty="easy", options=["a", "b", "c", "d"],
                                       correct_option_index=1, expected_concepts=None, rubric=None, starter_code=None, test_cases=None,
                                       allowed_languages=None, source_type="AI_GENERATED")
            ids.append(aq)
        fz.sections.append({"id": uuid.uuid4(), "title": f"skill {s}", "order_index": s, "aq_ids": ids})
    return fz


def test_one_question_sections_are_still_shuffled():
    fz = _fz(12, 1)  # what the assessment agent produces: a section per skill
    authored = [aq for s in fz.sections for aq in s["aq_ids"]]
    q1, _ = ver.new_layout(fz, {"randomize_questions": True, "randomize_options": True})
    q2, _ = ver.new_layout(fz, {"randomize_questions": True, "randomize_options": True})
    a1 = SimpleNamespace(question_order=q1, option_orders={})
    a2 = SimpleNamespace(question_order=q2, option_orders={})
    o1, o2 = ver.ordered_ids(a1, fz), ver.ordered_ids(a2, fz)
    assert sorted(o1) == sorted(authored) and o1 != authored and o1 != o2  # 1/12! chance of a false failure
    assert ver.ordered_ids(a1, fz) == o1  # reading it again never reshuffles


def test_disabled_keeps_authored_order_and_identity_options():
    fz = _fz(6, 2)
    authored = [aq for s in fz.sections for aq in s["aq_ids"]]
    q, o = ver.new_layout(fz, {"randomize_questions": False, "randomize_options": False})
    assert ver.ordered_ids(SimpleNamespace(question_order=q), fz) == authored
    assert all(perm == [0, 1, 2, 3] for perm in o.values())


def test_legacy_per_section_layout_is_still_readable():
    fz = _fz(3, 3)
    legacy = {str(s["id"]): [str(i) for i in reversed(s["aq_ids"])] for s in fz.sections}
    expect = [aq for s in fz.sections for aq in reversed(s["aq_ids"])]
    assert ver.ordered_ids(SimpleNamespace(question_order=legacy), fz) == expect
    assert ver.ordered_ids(SimpleNamespace(question_order=None), fz) == [aq for s in fz.sections for aq in s["aq_ids"]]
