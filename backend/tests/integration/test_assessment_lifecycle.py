"""Frozen versions, server-authoritative timer, persisted randomization, review marks, hidden data."""

import asyncio
import datetime as dt

import pytest
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.models.assessments import Assessment, AssessmentAttempt, AssessmentVersion
from app.models.evidence import SkillEvidence
from app.models.questions import Question
from app.services.assessments import versioning as ver
from tests.factories import make_application, make_company, make_job, make_student
from tests.integration.test_candidate_pipeline import _published_assessment


@pytest.fixture
async def ctx():
    async with AsyncSessionLocal() as db:
        org, rec, hc = await make_company(db, "LifeCo")
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        a, aqs, qs = await _published_assessment(db, org, job)
        await db.commit()
        return dict(a=str(a.id), app=str(app_.id), hs=hs, hc=hc, aqs=aqs, qs=qs, job=str(job.id))


async def _start(client, c):
    r = await client.post(f"/assessments/{c['a']}/attempts", headers=c["hs"], json={"application_id": c["app"]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_timer_is_server_side_and_survives_refresh_and_second_tab(client, ctx):
    aid = await _start(client, ctx)
    s1 = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    again = await client.post(f"/assessments/{ctx['a']}/attempts", headers=ctx["hs"], json={"application_id": ctx["app"]})
    assert again.json()["id"] == aid  # second tab: same attempt, same clock
    s2 = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    assert s1["expires_at"] == s2["expires_at"] and s1["started_at"] == s2["started_at"]
    dur = dt.datetime.fromisoformat(s1["expires_at"]) - dt.datetime.fromisoformat(s1["started_at"])
    assert dur >= dt.timedelta(minutes=5) and s1["server_time"]
    async with AsyncSessionLocal() as db:
        assert (await db.scalar(select(func.count()).select_from(AssessmentAttempt).where(AssessmentAttempt.id == aid))) == 1
        att = await db.get(AssessmentAttempt, aid)
        assert att.submitted_at is None and att.version_id is not None


@pytest.mark.asyncio
async def test_expired_attempt_rejects_writes_and_is_finalized_by_the_server(client, ctx, monkeypatch):
    aid = await _start(client, ctx)
    mcq = ctx["aqs"][0]
    ok = await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": str(mcq.id), "selected_option_index": 0})
    assert ok.status_code == 200
    future = ver.now() + dt.timedelta(hours=3)
    monkeypatch.setattr(ver, "now", lambda: future)
    late = await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": str(mcq.id), "selected_option_index": 1})
    assert late.status_code == 409 and late.json()["detail"]["code"] == "ATTEMPT_EXPIRED"
    sess = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()  # opening the page after the deadline
    assert sess["attempt"]["status"] == "SCORED" and sess["attempt"]["completed"]
    async with AsyncSessionLocal() as db:
        att = await db.get(AssessmentAttempt, aid)
        assert att.submitted_at is not None and att.submitted_at >= att.expires_at
        assert att.total_score is not None


@pytest.mark.asyncio
async def test_order_is_persisted_options_map_back_and_keys_never_leave(client, ctx):
    aid = await _start(client, ctx)
    s1 = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    s2 = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    ids = lambda s: [q["id"] for sec in s["sections"] for q in sec["questions"]]
    opts = lambda s: [q["question"]["options"] for sec in s["sections"] for q in sec["questions"]]
    assert ids(s1) == ids(s2) and opts(s1) == opts(s2)  # refresh never reshuffles
    assert sorted(ids(s1)) == sorted(str(x.id) for x in ctx["aqs"])
    blob = str(s1)
    for forbidden in ("correct_option_index", "test_cases", "rubric", "expected_concepts"):
        assert forbidden not in blob
    assert "[0]" not in blob  # the hidden coding test; only the visible samples are sent
    mcq_item = next(q for sec in s1["sections"] for q in sec["questions"] if q["question"]["question_type"] == "MCQ")
    shown = mcq_item["question"]["options"]
    assert sorted(shown) == ["emit", "return", "yield"]
    displayed_correct = shown.index("yield")  # the candidate picks what they see; the server maps it back
    await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": mcq_item["id"], "selected_option_index": displayed_correct})
    back = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    got = next(q for sec in back["sections"] for q in sec["questions"] if q["id"] == mcq_item["id"])
    assert got["answer"]["selected_option_index"] == displayed_correct
    async with AsyncSessionLocal() as db:
        from app.models.assessments import AssessmentAnswer
        row = await db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == aid))
        assert ctx["qs"][0].options[row.selected_option_index] == "yield"
    assert (await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"],
                             json={"assessment_question_id": mcq_item["id"], "selected_option_index": 9})).status_code == 422
    sub = await client.post(f"/assessments/attempts/{aid}/submit", headers=ctx["hs"])
    assert sub.status_code == 200
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == aid, AssessmentAnswer.selected_option_index.is_not(None)))
        assert row.is_correct is True  # graded on the original index


@pytest.mark.asyncio
async def test_randomization_can_be_disabled_by_the_recruiter_and_config_freezes_at_publish(client, ctx):
    async with AsyncSessionLocal() as db:
        await db.execute(update(Assessment).where(Assessment.id == ctx["a"]).values(status="DRAFT"))
        await db.commit()
    assert (await client.put(f"/assessments/{ctx['a']}/config", headers=ctx["hc"], json={"duration_minutes": 3})).status_code == 422
    assert (await client.put(f"/assessments/{ctx['a']}/config", headers=ctx["hs"], json={"duration_minutes": 30})).status_code == 403
    r = await client.put(f"/assessments/{ctx['a']}/config", headers=ctx["hc"], json={"duration_minutes": 30, "randomize_questions": False, "randomize_options": False})
    assert r.status_code == 200
    pub = await client.post(f"/assessments/{ctx['a']}/publish", headers=ctx["hc"])
    assert pub.status_code == 200
    assert (await client.put(f"/assessments/{ctx['a']}/config", headers=ctx["hc"], json={"duration_minutes": 90})).status_code == 409
    aid = await _start(client, ctx)
    s = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    assert [q["id"] for sec in s["sections"] for q in sec["questions"]] == [str(x.id) for x in ctx["aqs"]]  # authored order
    mcq = next(q for sec in s["sections"] for q in sec["questions"] if q["question"]["question_type"] == "MCQ")
    assert mcq["question"]["options"] == ["return", "yield", "emit"]
    assert dt.datetime.fromisoformat(s["expires_at"]) - dt.datetime.fromisoformat(s["started_at"]) == dt.timedelta(minutes=30)


@pytest.mark.asyncio
async def test_mark_for_review_persists(client, ctx):
    aid = await _start(client, ctx)
    q = ctx["aqs"][1]
    await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": str(q.id), "marked_for_review": True})
    s = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    item = next(x for sec in s["sections"] for x in sec["questions"] if x["id"] == str(q.id))
    assert item["answer"]["marked_for_review"] is True and item["answer"]["answer_text"] is None
    await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": str(q.id), "answer_text": "hello"})
    s = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    item = next(x for sec in s["sections"] for x in sec["questions"] if x["id"] == str(q.id))
    assert item["answer"]["marked_for_review"] is True and item["answer"]["answer_text"] == "hello"  # saving text keeps the mark


@pytest.mark.asyncio
async def test_bank_changes_after_start_do_not_change_the_attempt_and_double_submit_is_single(client, ctx):
    aid = await _start(client, ctx)
    mcq = ctx["aqs"][0]
    s = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    item = next(x for sec in s["sections"] for x in sec["questions"] if x["question"]["question_type"] == "MCQ")
    shown = item["question"]["options"]
    await client.put(f"/assessments/attempts/{aid}/answers", headers=ctx["hs"], json={"assessment_question_id": item["id"], "selected_option_index": shown.index("yield")})
    async with AsyncSessionLocal() as db:  # question bank edited after the attempt began: key changed, text changed, tests emptied
        await db.execute(update(Question).where(Question.id == ctx["qs"][0].id).values(correct_option_index=0, question_text="CHANGED", options=["x", "y"]))
        await db.execute(update(Question).where(Question.id == ctx["qs"][2].id).values(test_cases=[]))
        await db.commit()
    s2 = (await client.get(f"/assessments/attempts/{aid}", headers=ctx["hs"])).json()
    item2 = next(x for sec in s2["sections"] for x in sec["questions"] if x["id"] == item["id"])
    assert item2["question"]["question_text"] == item["question"]["question_text"] != "CHANGED"
    r1, r2 = await asyncio.gather(client.post(f"/assessments/attempts/{aid}/submit", headers=ctx["hs"]),
                                  client.post(f"/assessments/attempts/{aid}/submit", headers=ctx["hs"]))
    assert r1.status_code == r2.status_code == 200
    async with AsyncSessionLocal() as db:
        att = await db.get(AssessmentAttempt, aid)
        from app.models.assessments import AssessmentAnswer
        a = await db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == aid, AssessmentAnswer.selected_option_index.is_not(None)))
        assert a.is_correct is True  # graded against the frozen key, not the edited bank
        n = await db.scalar(select(func.count()).select_from(SkillEvidence).where(SkillEvidence.source_id == a.id))
        assert n == 1
        v = await db.get(AssessmentVersion, att.version_id)
        assert v.content_hash and v.version_no == 1


@pytest.mark.asyncio
async def test_written_answers_are_scored_concurrently_on_submit(client, monkeypatch):
    """Submit used to score written answers one after another (~4 s each in the browser E2E: a 16.6 s submit)."""
    import asyncio
    import time

    from app.api.v1 import assessments as api
    from app.models.assessments import AssessmentQuestion, AssessmentSection
    from app.models.enums import QuestionSourceType, QuestionStatus, QuestionType, Visibility
    from app.schemas.rubric import RubricEvaluation
    from tests.factories import skill

    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db, "ConcCo")
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db)
        app_ = await make_application(db, job, st)
        py = await skill(db, "Python")
        a = Assessment(job_id=job.id, title="t", status="PUBLISHED")
        db.add(a)
        await db.flush()
        sec = AssessmentSection(assessment_id=a.id, title="s", order_index=0)
        db.add(sec)
        await db.flush()
        aqs = []
        for i in range(4):
            q = Question(question_text=f"Explain concept number {i} in enough detail to be assessed.", question_type=QuestionType.TECHNICAL, skill_id=py.id,
                         difficulty="medium", source_type=QuestionSourceType.COMPANY_PRIVATE, organization_id=org.id, visibility=Visibility.COMPANY_PRIVATE,
                         status=QuestionStatus.APPROVED, expected_concepts=["a", "b"], rubric={"criteria": ["a"]})
            db.add(q)
            await db.flush()
            aq = AssessmentQuestion(assessment_id=a.id, section_id=sec.id, question_id=q.id, order_index=i)
            db.add(aq)
            aqs.append(aq)
        await db.commit()

    calls = []

    class FakeGW:
        model = "fake"

        async def evaluate_rubric(self, text, rubric, schema, **kw):
            calls.append(time.perf_counter())
            await asyncio.sleep(0.6)
            return RubricEvaluation(concept_accuracy=0.7, reasoning=0.7, completeness=0.7, communication=0.7,
                                    demonstrated_concepts=[], missing_concepts=[], evaluator_confidence=0.9)
    monkeypatch.setattr(api, "get_ai_gateway", lambda: FakeGW())
    att = (await client.post(f"/assessments/{a.id}/attempts", headers=hs, json={"application_id": str(app_.id)})).json()
    for aq in aqs:
        await client.put(f"/assessments/attempts/{att['id']}/answers", headers=hs, json={"assessment_question_id": str(aq.id), "answer_text": "A reasonably long answer. " * 5})
    t = time.perf_counter()
    r = await client.post(f"/assessments/attempts/{att['id']}/submit", headers=hs)
    took = time.perf_counter() - t
    assert r.status_code == 200 and len(calls) == 4
    assert took < 1.8, took  # sequential would be >= 2.4 s
    assert max(calls) - min(calls) < 0.3  # the four scoring calls overlapped
    async with AsyncSessionLocal() as db:
        from app.models.assessments import AssessmentAnswer
        rows = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == att["id"]))).all()
        assert all(x.rubric_evaluation is not None and x.score is not None for x in rows)
