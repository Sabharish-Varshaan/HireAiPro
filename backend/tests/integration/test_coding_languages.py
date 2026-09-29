"""Coding through HireAiPro's real /coding/submit endpoint: three languages via
Judge0 (ids from /languages), per-question language rules, hidden tests, and
EXECUTION_SERVICE_UNAVAILABLE instead of host execution."""
import httpx
import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.coding import CodingSubmission
from app.models.evidence import SkillEvidence
from app.services.coding import judge0_client as jc
from tests.factories import make_company, make_job, make_student
from tests.integration.test_candidate_pipeline import _judge0_up, _published_assessment

SOLUTIONS = {  # sum of a JSON-style list read from stdin
    "python": "import ast,sys\nprint(sum(ast.literal_eval(sys.stdin.read())))\n",
    "javascript": "const n=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(n.reduce((a,b)=>a+b,0));\n",
    "cpp": ("#include <bits/stdc++.h>\nusing namespace std;\nint main(){string s,t;getline(cin,s);long sum=0;"
            "for(char&c:s)if(c=='['||c==']'||c==',')c=' ';stringstream ss(s);long x;while(ss>>x)sum+=x;cout<<sum<<endl;}\n"),
}
WRONG = {"python": "print(6)\n", "javascript": "console.log(6)\n", "cpp": "#include <iostream>\nint main(){std::cout<<6<<std::endl;}\n"}


async def _setup(client, allowed=None, mutate=None):
    async with AsyncSessionLocal() as db:
        org, rec, _ = await make_company(db)
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        st, _, hs = await make_student(db)
        a, aqs, qs = await _published_assessment(db, org, job)
        qs[2].allowed_languages = allowed
        if mutate:
            mutate(qs[2])
        await db.commit()
    app_id = (await client.post("/applications", headers=hs, json={"job_id": str(job.id)})).json()["id"]
    attempt = (await client.post(f"/assessments/{a.id}/attempts", headers=hs, json={"application_id": app_id})).json()
    saved = (await client.put(f"/assessments/attempts/{attempt['id']}/answers", headers=hs,
                              json={"assessment_question_id": str(aqs[2].id), "answer_text": ""})).json()
    detail = (await client.get(f"/assessments/attempts/{attempt['id']}", headers=hs)).json()  # frozen attempt session
    return st, hs, saved["answer_id"], qs[2], detail


@pytest.mark.asyncio
async def test_unavailable_runner_returns_503_and_scores_nothing(client, monkeypatch):
    st, hs, answer_id, q, _ = await _setup(client)

    async def down(*a, **k):
        raise jc.ExecutionUnavailable("ConnectError: refused")
    monkeypatch.setattr(jc.Judge0Client, "run_many", down)
    r = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": answer_id, "question_id": str(q.id),
                                                             "language": "python", "source_code": SOLUTIONS["python"]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "EXECUTION_SERVICE_UNAVAILABLE"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(CodingSubmission.id)).where(CodingSubmission.question_id == q.id)) == 0
        assert await db.scalar(select(func.count(SkillEvidence.id)).where(SkillEvidence.student_id == st.id)) == 0


@pytest.mark.asyncio
async def test_question_language_rules_and_hidden_tests(client):
    _, hs, answer_id, q, detail = await _setup(client, allowed=["cpp"])
    code_q = [x["question"] for s in detail["sections"] for x in s["questions"] if x["question"]["question_type"] == "CODING"][0]
    assert code_q["allowed_languages"] == ["cpp"] and "test_cases" not in code_q
    r = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": answer_id, "question_id": str(q.id),
                                                             "language": "python", "source_code": "print(1)"})
    assert r.status_code == 422
    r = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": answer_id, "question_id": str(q.id),
                                                             "language": "ruby", "source_code": "p 1"})
    assert r.status_code == 422


@pytest.mark.judge0
@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["python", "javascript", "cpp"])
async def test_three_languages_through_endpoint_and_judge0(client, lang):
    assert _judge0_up()
    from app.core.config import get_settings
    live = {l["name"]: l["id"] for l in httpx.get(f"{get_settings().JUDGE0_URL}/languages").json()}
    st, hs, answer_id, q, _ = await _setup(client)

    wrong = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": answer_id, "question_id": str(q.id),
                                                                 "language": lang, "source_code": WRONG[lang]})
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["result"] == "SOME_TESTS_FAILED" and "passed_count" not in wrong.json()  # students see status only
    async with AsyncSessionLocal() as db:  # [1,2,3] and [10,-4] sum to 6; [0] does not
        w = await db.get(CodingSubmission, wrong.json()["submission_id"])
        assert (w.passed_count, w.total_count) == (2, 3)

    ok = await client.post("/coding/submit", headers=hs, json={"assessment_answer_id": answer_id, "question_id": str(q.id),
                                                              "language": lang, "source_code": SOLUTIONS[lang]})
    body = ok.json()
    assert ok.status_code == 200 and body["result"] == "ALL_TESTS_PASSED", body
    assert body["execution_backend"] == "judge0" and body["language"] == lang
    async with AsyncSessionLocal() as db:
        sub = await db.get(CodingSubmission, body["submission_id"])
        assert sub.judge0_language_id in live.values()
        assert (sub.language, sub.execution_backend, sub.passed_count) == (lang, "judge0", 3)
        ev = await db.scalar(select(SkillEvidence).where(SkillEvidence.student_id == st.id, SkillEvidence.source_type == "CODING"))
        assert ev.source_id == sub.id and ev.normalized_score == 1.0 and ev.raw_score == 3.0  # from Judge0 pass counts only


@pytest.mark.asyncio
async def test_generated_starter_code_is_never_shown_to_students(client):
    from app.models.enums import QuestionSourceType

    def make_generated(q):
        q.source_type, q.starter_code = QuestionSourceType.AI_GENERATED, "def solve():\n    return the_full_answer()\n"

    _, _, _, _, kept = await _setup(client)
    code = lambda d: [x["question"] for s in d["sections"] for x in s["questions"] if x["question"]["question_type"] == "CODING"][0]  # noqa: E731
    assert code(kept)["starter_code"] == "import ast,sys\n"  # recruiter-written starter is kept
    _, _, _, _, hidden = await _setup(client, mutate=make_generated)
    assert code(hidden)["starter_code"] is None and "test_cases" not in code(hidden)


@pytest.mark.asyncio
async def test_concurrent_saves_for_one_question_create_one_answer(client):
    import asyncio

    from app.models.assessments import AssessmentAnswer

    _, hs, answer_id, q, detail = await _setup(client)
    async with AsyncSessionLocal() as db:
        from app.models.assessments import AssessmentQuestion
        aq = await db.scalar(select(AssessmentQuestion).where(AssessmentQuestion.question_id == q.id))
        attempt_id = (await db.get(AssessmentAnswer, answer_id)).attempt_id
    # a different question of the same attempt, hit twice at the same instant
    other = [x for s in detail["sections"] for x in s["questions"] if x["id"] != str(aq.id)][0]["id"]
    body = {"assessment_question_id": other, "answer_text": "x"}
    r1, r2 = await asyncio.gather(client.put(f"/assessments/attempts/{attempt_id}/answers", headers=hs, json=body),
                                  client.put(f"/assessments/attempts/{attempt_id}/answers", headers=hs, json=body))
    assert r1.status_code == r2.status_code == 200 and r1.json()["answer_id"] == r2.json()["answer_id"]
    async with AsyncSessionLocal() as db:
        n = await db.scalar(select(func.count(AssessmentAnswer.id)).where(
            AssessmentAnswer.attempt_id == attempt_id, AssessmentAnswer.assessment_question_id == other))
    assert n == 1


@pytest.mark.asyncio
async def test_submit_uses_latest_run_across_legacy_duplicate_answers(client, monkeypatch):
    from app.models.assessments import AssessmentAnswer
    from app.models.coding import CodingSubmission
    from app.services.evidence.service import record_evidence
    from app.models.enums import EvidenceSourceType
    from tests.fakes import FakeLLM, rubric

    FakeLLM(monkeypatch, {"RubricEvaluation": rubric(0.5, 0.8)})
    st, hs, answer_id, q, _ = await _setup(client)
    async with AsyncSessionLocal() as db:
        first = await db.get(AssessmentAnswer, answer_id)
        dup = AssessmentAnswer(attempt_id=first.attempt_id, assessment_question_id=first.assessment_question_id)  # the old race
        db.add(dup)
        await db.flush()
        subs = []
        for ans, passed in ((first, 1), (dup, 3)):  # older run 1/3, latest run 3/3 on the duplicate row
            s = CodingSubmission(assessment_answer_id=ans.id, question_id=q.id, language="python", source_code=f"# {passed}",
                                 status="COMPLETED", passed_count=passed, total_count=3, score=passed / 3)
            db.add(s)
            await db.flush()
            await record_evidence(db, st.id, q.skill_id, EvidenceSourceType.CODING, passed / 3, source_id=s.id,
                                  raw_score=float(passed), idempotency_key=f"CODING:answer:{ans.id}")
            subs.append(s)
            await db.commit()  # separate requests in reality -> distinct created_at
        attempt_id = first.attempt_id
    r = await client.post(f"/assessments/attempts/{attempt_id}/submit", headers=hs)
    assert r.status_code == 200, r.text
    from app.models.evidence import SkillEvidence
    async with AsyncSessionLocal() as db:
        live = (await db.scalars(select(SkillEvidence).where(SkillEvidence.student_id == st.id, SkillEvidence.source_type == "CODING",
                                                             SkillEvidence.is_deleted.is_(False)))).all()
        answers = (await db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id,
                                                                   AssessmentAnswer.assessment_question_id == first.assessment_question_id))).all()
    assert [e.source_id for e in live] == [subs[1].id]  # only the latest run counts
    assert max(a.score or 0 for a in answers) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rejecting_a_question_retires_its_evidence(client):
    from app.models.coding import CodingSubmission
    from app.models.enums import EvidenceSourceType, QuestionStatus
    from app.models.evidence import SkillEvidence
    from app.services.evidence.service import record_evidence
    from tests.factories import make_company, make_job, make_student
    from tests.integration.test_candidate_pipeline import _published_assessment

    async with AsyncSessionLocal() as db:
        org, rec, hr = await make_company(db)
        job = await make_job(db, org, rec, [("Python", "required", 0.6, 1.0)])
        st, _, _ = await make_student(db)
        a, aqs, qs = await _published_assessment(db, org, job)
        qs[2].status = QuestionStatus.VALIDATED
        from app.models.applications import Application
        from app.models.assessments import AssessmentAnswer, AssessmentAttempt
        app_ = Application(job_id=job.id, student_id=st.id, status="ASSESSMENT_PENDING")
        db.add(app_)
        await db.flush()
        att = AssessmentAttempt(assessment_id=a.id, application_id=app_.id, student_id=st.id)
        db.add(att)
        await db.flush()
        ans = AssessmentAnswer(attempt_id=att.id, assessment_question_id=aqs[2].id, answer_text="x")
        db.add(ans)
        await db.flush()
        s = CodingSubmission(question_id=qs[2].id, language="cpp", source_code="x", status="COMPLETED",
                             passed_count=2, total_count=3, score=2 / 3, assessment_answer_id=ans.id)
        db.add(s)
        await db.flush()
        await record_evidence(db, st.id, qs[2].skill_id, EvidenceSourceType.CODING, 2 / 3, source_id=s.id, raw_score=2.0)
        await db.commit()
    r = await client.post(f"/questions/{qs[2].id}/transition", headers=hr,
                          json={"status": "REJECTED", "reason": "tests proven wrong by execution"})
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as db:
        ev = await db.scalar(select(SkillEvidence).where(SkillEvidence.source_id == s.id))
    assert ev.is_deleted


@pytest.mark.asyncio
async def test_run_uses_only_visible_samples_and_creates_no_submission(client, monkeypatch):
    from app.api.v1 import coding as coding_api

    seen = {"tests": None, "custom": None}

    async def run_many(self, src, lang, tests):
        seen["tests"] = [t["input"] for t in tests]
        return [{"status": {"id": 3, "description": "Accepted"}, "stdout": t["expected_output"]} for t in tests]

    async def run(self, src, lang, stdin="", expected_output=None):
        seen["custom"] = stdin
        return {"status": {"id": 3, "description": "Accepted"}, "stdout": "echo:" + stdin}
    monkeypatch.setattr(jc.Judge0Client, "run_many", run_many)
    monkeypatch.setattr(jc.Judge0Client, "run", run)
    monkeypatch.setattr(coding_api, "RUN_SPACING_SECONDS", 0.0)
    st, hs, answer_id, q, detail = await _setup(client)
    code = [x["question"] for s in detail["sections"] for x in s["questions"] if x["question"]["question_type"] == "CODING"][0]
    assert [s["input"] for s in code["sample_tests"]] == ["[1, 2, 3]", "[10, -4]"] and code["hidden_test_count"] == 1
    assert "[0]" not in str(code)  # the hidden test never reaches the browser
    body = {"assessment_answer_id": answer_id, "question_id": str(q.id), "language": "python", "source_code": "print(6)", "custom_input": "[7]"}
    r = await client.post("/coding/run", headers=hs, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert seen["tests"] == ["[1, 2, 3]", "[10, -4]"] and seen["custom"] == "[7]"  # samples only; hidden test not executed
    assert [s["passed"] for s in out["samples"]] == [True, True] and out["custom"]["stdout"] == "echo:[7]"
    assert "[0]" not in r.text
    async with AsyncSessionLocal() as db:  # a Run is not a submission and produces no evidence
        assert await db.scalar(select(func.count(CodingSubmission.id)).where(CodingSubmission.question_id == q.id)) == 0
        assert await db.scalar(select(func.count(SkillEvidence.id)).where(SkillEvidence.student_id == st.id)) == 0
    bad = await client.post("/coding/run", headers=hs, json={**body, "language": "ruby"})
    assert bad.status_code == 422
    big = await client.post("/coding/run", headers=hs, json={**body, "custom_input": "x" * 20000})
    assert big.status_code == 422


@pytest.mark.asyncio
async def test_run_is_rate_limited_per_attempt(client, monkeypatch):
    async def run_many(self, src, lang, tests):
        return [{"status": {"id": 3, "description": "Accepted"}, "stdout": ""} for _ in tests]
    monkeypatch.setattr(jc.Judge0Client, "run_many", run_many)
    _, hs, answer_id, q, _ = await _setup(client)
    body = {"assessment_answer_id": answer_id, "question_id": str(q.id), "language": "python", "source_code": "print(6)"}
    assert (await client.post("/coding/run", headers=hs, json=body)).status_code in (200, 429)
    assert (await client.post("/coding/run", headers=hs, json=body)).status_code == 429
