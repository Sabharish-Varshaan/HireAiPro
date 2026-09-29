#!/usr/bin/env python3
"""HireAiPro quickfire E2E: a fast integrity check of the RUNNING system (see docs/QUICKFIRE_E2E.md).

    backend/.venv/bin/python scripts/quickfire_e2e.py

It talks to the real API over HTTP (default http://localhost:8020/api/v1) and only uses product endpoints: it never writes to the database,
never mocks a service and never fakes a score. Question content is created through the product's own question API with answers the script
knows, so scoring is checked against real results. Judge0 is exercised for real; if it is unavailable the coding round is reported BLOCKED
(never simulated on the host).

Exit codes: 0 PASS, 1 FAIL (application/system regression or a required dependency down), 2 DEGRADED (only Judge0/Ollama blocked).
"""
import datetime as dt
import json
import os
import re
import secrets
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(os.path.join(ROOT, "backend"))  # settings read backend/.env: the script must see the same configuration as the API and worker
BASE = os.environ.get("QUICKFIRE_API", "http://localhost:8020/api/v1")
RUN = "QF_" + dt.datetime.now().strftime("%Y%m%d%H%M%S")
PW = "Qf-" + secrets.token_urlsafe(12)  # generated per run, never stored or printed
GEN_TIMEOUT = int(os.environ.get("QUICKFIRE_GEN_TIMEOUT", "240"))

http = httpx.Client(base_url=BASE, timeout=120)
results: dict[str, tuple[str, str]] = {}
state: dict = {}


class Blocked(Exception):
    pass


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def api(method, path, tok=None, expect=(200, 201, 202), **kw):
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = http.request(method, path, headers=h, **kw)
    if expect and r.status_code not in expect:
        raise Fail(f"{method} {path} -> {r.status_code} {r.text[:200]}")
    return r


def set_result(name, status, detail=""):
    results[name] = (status, detail)


def step(name, fn, *, required=True):
    """Runs one check. A failure of a required step stops the run (fail fast)."""
    t = time.time()
    try:
        detail = fn() or ""
        set_result(name, "PASS", detail)
        print(f"  PASS     {name:<24}{detail}  ({time.time() - t:.1f}s)", flush=True)
    except Blocked as e:
        set_result(name, "BLOCKED", str(e))
        print(f"  BLOCKED  {name:<24}{e}", flush=True)
    except (Fail, httpx.HTTPError, KeyError, IndexError, AssertionError) as e:
        set_result(name, "FAIL", f"{type(e).__name__}: {e}"[:300])
        print(f"  FAIL     {name:<24}{type(e).__name__}: {e}"[:400], flush=True)
        if required:
            finish(stopped=name)


# ------------------------------------------------------------------ preflight
def pre_api():
    api("GET", "/skills")
    return BASE


def pre_valkey():
    import redis
    from app.core.config import get_settings

    redis.Redis.from_url(get_settings().VALKEY_URL, socket_connect_timeout=3).ping()


def pre_worker():
    from app.workers.celery_app import celery_app

    replies = celery_app.control.ping(timeout=4)
    check(replies, "no Celery worker answered a ping")
    return f"{len(replies)} worker"


def pre_qdrant():
    from app.core.config import get_settings

    r = httpx.get(get_settings().QDRANT_URL.rstrip("/") + "/collections", timeout=5)
    check(r.status_code == 200, f"Qdrant HTTP {r.status_code}")


def pre_providers():
    from app.services.ai_gateway.providers import configured_providers

    names = sorted(configured_providers())
    check(names, "no model provider is configured")
    return "configured: " + ", ".join(names)


def pre_ollama():
    from app.core.config import get_settings

    s = get_settings()
    try:
        r = httpx.get(s.OLLAMA_BASE_URL.rstrip("/") + "/api/tags", timeout=4)
    except httpx.HTTPError as e:
        raise Blocked(f"Ollama unreachable at {s.OLLAMA_BASE_URL} (optional fallback provider): {type(e).__name__}")
    check(r.status_code == 200, f"Ollama HTTP {r.status_code}")
    check(any(m["name"] == s.OLLAMA_MODEL for m in r.json().get("models", [])), f"model {s.OLLAMA_MODEL} not pulled")
    return s.OLLAMA_MODEL


def pre_judge0():
    """Runs one tiny real submission through Judge0 and reads the result. Any failure here makes coding BLOCKED."""
    from app.core.config import get_settings

    url = get_settings().JUDGE0_URL.rstrip("/")
    try:
        r = httpx.post(url + "/submissions?base64_encoded=false", json={"source_code": "print(6*7)", "language_id": 71}, timeout=10)
        token = r.json()["token"]
        for _ in range(20):
            d = httpx.get(f"{url}/submissions/{token}?base64_encoded=false", timeout=10).json()
            if d["status"]["id"] > 2:
                break
            time.sleep(0.5)
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise Blocked(f"Judge0 unreachable at {url}: {type(e).__name__}")
    if d["status"]["id"] == 3 and (d.get("stdout") or "").strip() == "42":
        state["judge0"] = True
        return "sandbox executed a program"
    msg = (d.get("message") or d["status"]["description"])[:120]
    hint = " (isolate box id > 999: run scripts/judge0_reset_ids.sh)" if "range" in str(d) or "script" in msg else ""
    raise Blocked(f"Judge0 cannot execute code: {msg}{hint}")


# ------------------------------------------------------------------ accounts
def signup(role, email, name, **extra):
    r = api("POST", "/auth/signup", json={"email": email, "password": PW, "full_name": name, "role": role, **extra})
    return r.json()["access_token"]


def login(email):
    return api("POST", "/auth/login", json={"email": email, "password": PW}).json()["access_token"]


def outbox_token(email):
    items = api("GET", "/dev/email-outbox").json()
    items = items if isinstance(items, list) else items.get("items", [])
    for it in items:
        blob = json.dumps(it)
        if email in blob:
            m = re.search(r"token=([A-Za-z0-9_\-]+)", blob)
            if m:
                return m.group(1)
    raise Fail("invitation email not found in the development outbox")


def accounts():
    e = lambda role: f"{role}.{RUN.lower()}@example.com"
    state["po"] = signup("PLACEMENT_OFFICER", e("po"), "QF Officer", institution_name=f"Quickfire Institute {RUN}")
    state["inst"] = api("GET", "/institutions/mine", state["po"]).json()[0]["id"]
    iid = state["inst"]
    dep = api("POST", f"/institutions/{iid}/departments", state["po"], json={"name": "Computer Science"}).json()
    coh = api("POST", f"/institutions/{iid}/cohorts", state["po"], json={"name": "CSE 2027", "department_id": dep["id"], "graduation_year": 2027}).json()
    state["dept"], state["cohort"] = dep["id"], coh["id"]
    state["stu_email"] = e("student")
    api("POST", f"/institutions/{iid}/student-records/invite", state["po"], json={
        "email": state["stu_email"], "first_name": "Quick", "last_name": "Fire", "student_id": "QF-1", "department": "Computer Science",
        "cohort": "CSE 2027", "graduation_year": "2027"})
    tok = outbox_token(state["stu_email"])
    api("POST", "/auth/invitations/accept", json={"token": tok, "password": PW, "full_name": "Quick Fire"})
    state["stu"] = login(state["stu_email"])
    state["outsider"] = signup("STUDENT", e("outsider"), "QF Outsider")  # independent student: not enrolled anywhere
    state["coA"] = signup("RECRUITER", e("companya"), "QF Recruiter A", company_name=f"QF Company A {RUN}")
    state["coB"] = signup("RECRUITER", e("companyb"), "QF Recruiter B", company_name=f"QF Company B {RUN}")
    api("GET", "/auth/me", state["stu"])
    return "officer, invited student (claimed), outsider student, two companies"


# ------------------------------------------------------------------ job + question bank
SOLUTION = "a, b = map(int, input().split())\nprint(a + b)\n"
TESTS = [{"input": i, "expected_output": str(sum(map(int, i.split()))), "visible": v, "category": c} for i, v, c in
         [("1 2", True, "normal"), ("10 20", True, "normal"), ("0 0", False, "edge"), ("-5 5", False, "negative"), ("100 250", False, "large"),
          ("7 8", False, "normal"), ("-3 -4", False, "negative"), ("999 1", False, "boundary")]]


def job_and_bank():
    co = state["coA"]
    deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).isoformat()
    org = api("GET", "/organizations/mine", co).json()[0]["id"]
    job = api("POST", "/jobs", co, params={"organization_id": org}, json={"title": f"QF Backend Engineer {RUN}", "employment_type": "FULL_TIME", "work_mode": "REMOTE",
                                         "number_of_openings": 2, "application_deadline": deadline, "experience_level": "FRESHER"}).json()
    state["job"] = job["id"]
    api("PUT", f"/jobs/{job['id']}/jd", co, json={"description_raw": "Backend engineer. Required skill: Python. You will write and debug Python services."})
    api("POST", f"/jobs/{job['id']}/process", co)
    deadline_t = time.time() + 120
    while time.time() < deadline_t:
        p = api("GET", f"/jobs/{job['id']}/processing", co).json().get("jd") or {}
        if p.get("status") == "COMPLETED":
            break
        check(p.get("status") != "FAILED", f"requirement extraction failed: {str(p.get('error'))[:120]}")
        time.sleep(3)
    else:
        raise Fail("requirement extraction did not finish in 120 s")
    j = api("GET", f"/jobs/{job['id']}", co).json()
    mapped = [s for s in j["skills"] if s.get("skill_id")]
    check(mapped, "extraction produced no mapped skill")
    keep = next((s for s in mapped if "python" in (s.get("raw_skill_name") or "").lower()), mapped[0])
    state["skill"] = keep["raw_skill_name"]
    payload = [{"id": s["id"], "skill_id": s.get("skill_id"), "raw_skill_name": s["raw_skill_name"], "requirement_type": "required",
                "minimum_level": 0.5, "importance": 0.9, "delete": s["id"] != keep["id"]} for s in j["skills"]]
    api("PUT", f"/jobs/{job['id']}/requirements/confirm", co, json={"skills": payload})

    # company-private content with answers this script knows (one distinctive marker for the isolation check)
    state["mcq"] = {}
    technical = [(f"QF_PRIVATE_{RUN} which Python keyword turns a function into a generator?", ["return", "yield", "emit"], 1),
                 (f"QF_PRIVATE_{RUN} which built-in function returns the number of items in a list?", ["size", "count_all", "len"], 2)]
    for text, opts, correct in technical:
        r = api("POST", "/questions", co, json={"question_text": text, "question_type": "MCQ", "skill": state["skill"], "difficulty": "medium",
                                                "options": opts, "correct_option": correct}).json()
        check(r["created"] == 1, f"private MCQ not created: {r}")
        state["mcq"][text] = opts[correct]
        state.setdefault("marker_id", r["question_ids"][0])
    for i in (1, 2):
        text = f"QF_APT_{RUN} what is {i + 6} multiplied by 7?"
        r = api("POST", "/questions", co, json={"question_text": text, "question_type": "MCQ", "domain": "APTITUDE", "category": "Quantitative Aptitude",
                                                "difficulty": "medium", "options": [str((i + 6) * 7 - 7), str((i + 6) * 7), str((i + 6) * 7 + 7)], "correct_option": 1}).json()
        check(r["created"] == 1, f"aptitude question not created: {r}")
        state["mcq"][text] = str((i + 6) * 7)
    r = api("POST", "/questions", co, json={"question_text": f"QF_CODE_{RUN}: read two integers a and b from one line and print a + b.", "question_type": "CODING",
                                            "skill": state["skill"], "difficulty": "easy", "test_cases": TESTS, "allowed_languages": ["python"],
                                            "starter_code": "# read one line: a b\n"}).json()
    check(r["created"] == 1, f"coding question not created: {r}")
    return f"skill {state['skill']}; 2 technical MCQ, 2 aptitude MCQ, 1 coding problem in the private bank"


def isolation():
    b, mid = state["coB"], state["marker_id"]
    r = api("GET", "/questions", b, params={"q": f"QF_PRIVATE_{RUN}"}).json()
    check(not r, "Company B can list Company A's private question")
    api("GET", f"/questions/{mid}", b, expect=(404,))
    api("GET", f"/questions/{mid}", state["coA"])
    api("GET", f"/hiring-pipeline/jobs/{state['job']}", b, expect=(403, 404))
    api("GET", f"/jobs/{state['job']}", b, expect=(403, 404))
    return "Company B: list empty, direct read 404, job/pipeline 403/404"


# ------------------------------------------------------------------ pipeline
def stage(t, **kw):
    return {"stage_type": t, "enabled": True, "proctored": False, **kw}


def configure_pipeline():
    co, job = state["coA"], state["job"]
    body = {"stages": [
        stage("APTITUDE_ASSESSMENT", duration_minutes=10, question_count=2, pass_threshold=50, auto_qualify=True,
              config={"categories": {"Quantitative Aptitude": 100}, "difficulty": {"easy": 0, "medium": 100, "hard": 0}, "shuffle_questions": False, "shuffle_options": False}),
        stage("TECHNICAL_ASSESSMENT", duration_minutes=10, question_count=2, pass_threshold=100, auto_qualify=True,
              config={"mcq_share": 100, "difficulty": {"easy": 0, "medium": 100, "hard": 0}, "shuffle_questions": False, "shuffle_options": False}),
        stage("CODING_ASSESSMENT", duration_minutes=15, question_count=1, required=False, pass_threshold=50, auto_qualify=True,
              config={"languages": ["python"], "difficulty": "easy", "shuffle_questions": False, "shuffle_options": False}),
        stage("TECHNICAL_INTERVIEW", duration_minutes=30, question_count=3, config={"min_questions": 3, "max_questions": 3}),
        stage("HR_INTERVIEW", duration_minutes=15, question_count=3,
              config={"categories": ["communication", "collaboration", "availability and logistics"], "min_questions": 3, "max_questions": 3}),
    ]}
    r = api("PUT", f"/hiring-pipeline/jobs/{job}", co, json=body).json()
    check(len([s for s in r["stages"] if s["enabled"]]) == 5, "not all five stages enabled")
    for t in ("APTITUDE_ASSESSMENT", "TECHNICAL_ASSESSMENT", "CODING_ASSESSMENT", "TECHNICAL_INTERVIEW", "HR_INTERVIEW"):
        api("POST", f"/hiring-pipeline/jobs/{job}/stages/{t}/generate", co)
    t0 = time.time()
    while time.time() - t0 < GEN_TIMEOUT:
        g = {x["stage_type"]: x for x in api("GET", f"/hiring-pipeline/jobs/{job}/generation", co).json()}
        if len(g) == 5 and all(x["status"] in ("COMPLETED", "FAILED") for x in g.values()):
            break
        time.sleep(4)
    else:
        raise Fail(f"stage preparation did not finish in {GEN_TIMEOUT} s: {[(k, v['status']) for k, v in g.items()]}")
    failed = {k: v["error"] for k, v in g.items() if v["status"] == "FAILED"}
    check(not failed, f"stage preparation failed: {failed}")
    view = api("GET", f"/hiring-pipeline/jobs/{job}", co).json()
    check(all(s["readiness"]["state"] == "READY" for s in view["stages"] if s["enabled"]), f"not every stage is ready: {view['issues']}")
    return f"5 stages ready in {time.time() - t0:.0f}s"


def publish_and_eligibility():
    co, po, iid, job = state["coA"], state["po"], state["inst"], state["job"]
    api("PUT", f"/jobs/{job}/distribution", co, json={"distribution_type": "INSTITUTION", "institution_id": iid})
    api("POST", f"/hiring-pipeline/jobs/{job}/publish", co)
    ops = api("GET", f"/institutions/{iid}/opportunities", po, params={"status": "PENDING"}).json()
    check(any(o["job_id"] == job for o in ops), "the opportunity did not reach the placement officer's queue")
    api("GET", f"/jobs/{job}", state["stu"], expect=(403, 404))  # not visible before approval
    api("POST", f"/institutions/{iid}/opportunities/{job}/approve", po,
        json={"department_ids": [state["dept"]], "cohort_ids": [state["cohort"]], "graduation_years": [2027]})
    feed = api("GET", "/jobs", state["stu"]).json()
    check(any(j["id"] == job for j in feed), "the eligible student does not see the approved job")
    out_feed = api("GET", "/jobs", state["outsider"]).json()
    check(not any(j["id"] == job for j in out_feed), "an outsider student sees a campus-only job")
    api("POST", "/applications", state["outsider"], json={"job_id": job}, expect=(403, 404))
    app = api("POST", "/applications", state["stu"], json={"job_id": job}).json()
    state["app"] = app["id"]
    return "approved by the officer; eligible student applied; outsider blocked"


# ------------------------------------------------------------------ rounds
def journey(tok=None):
    return api("GET", f"/hiring-pipeline/applications/{state['app']}", tok or state["stu"]).json()


def stg(j, t):
    return next(s for s in j["stages"] if s["stage_type"] == t)


def take_mcqs(assessment_id, wrong_one=False):
    att = api("POST", f"/assessments/{assessment_id}/attempts", state["stu"], json={"application_id": state["app"]}).json()["id"]
    sess = api("GET", f"/assessments/attempts/{att}", state["stu"]).json()
    qs = [q for s in sess["sections"] for q in s["questions"]]
    blob = json.dumps(sess)
    check("correct_option_index" not in blob and "explanation" not in blob, "answer key leaked to the student")
    for n, q in enumerate(qs):
        text = q["question"]["question_text"]
        check(text in state["mcq"], f"unexpected question in the stage: {text[:60]}")
        opts = q["question"]["options"]
        pick = opts.index(state["mcq"][text])
        if wrong_one and n == 0:
            pick = (pick + 1) % len(opts)
        api("PUT", f"/assessments/attempts/{att}/answers", state["stu"], json={"assessment_question_id": q["id"], "selected_option_index": pick})
    api("POST", f"/assessments/attempts/{att}/submit", state["stu"])
    return att


def aptitude():
    j = journey()
    check([s["status"] for s in j["stages"]][:2] == ["AVAILABLE", "LOCKED"], "unexpected initial stage states")
    take_mcqs(stg(j, "APTITUDE_ASSESSMENT")["assessment_id"])
    j = journey()
    r = stg(j, "APTITUDE_ASSESSMENT")["round"]
    check(r["decision"] == "QUALIFIED" and r["score"] == 100.0 and r["threshold"] == 50.0, f"aptitude round result: {r}")
    check(stg(j, "TECHNICAL_ASSESSMENT")["status"] == "AVAILABLE", "technical round did not unlock")
    return "score 100 >= 50: qualified, technical unlocked"


def technical_and_override():
    j = journey()
    take_mcqs(stg(j, "TECHNICAL_ASSESSMENT")["assessment_id"], wrong_one=True)  # 1 of 2 = 50 < 100
    j = journey()
    r = stg(j, "TECHNICAL_ASSESSMENT")["round"]
    check(r["decision"] == "NOT_QUALIFIED" and r["score"] == 50.0 and r["threshold"] == 100.0, f"technical round result: {r}")
    coding = stg(j, "CODING_ASSESSMENT")
    check(coding["status"] == "LOCKED", "coding is not locked after a failed round")
    code_id = coding["assessment_id"]
    lock = api("POST", f"/assessments/{code_id}/attempts", state["stu"], json={"application_id": state["app"]}, expect=(409,))
    check(lock.json()["detail"]["code"] == "STAGE_LOCKED", "locked round was not refused by the server")
    api("POST", f"/hiring-pipeline/applications/{state['app']}/stages/TECHNICAL_ASSESSMENT/override", state["coA"], expect=(409,),
        json={"decision": "ADVANCE", "reason": " "})  # a reason is mandatory
    o = api("POST", f"/hiring-pipeline/applications/{state['app']}/stages/TECHNICAL_ASSESSMENT/override", state["coA"],
            json={"decision": "ADVANCE", "reason": f"{RUN}: quickfire override"}).json()
    check(o["score"] == 50.0 and o["threshold"] == 100.0 and o["automatic_decision"] == "NOT_QUALIFIED" and o["override"]["decision"] == "ADVANCED", f"override record: {o}")
    check(stg(journey(), "CODING_ASSESSMENT")["status"] == "AVAILABLE", "coding did not unlock after the override")
    return "50 < 100: not qualified, coding locked (409), override recorded, coding unlocked"


def coding():
    if not state.get("judge0"):
        raise Blocked("Judge0 cannot execute code; the (optional) coding round is skipped, not simulated")
    j = journey()
    aid = stg(j, "CODING_ASSESSMENT")["assessment_id"]
    att = api("POST", f"/assessments/{aid}/attempts", state["stu"], json={"application_id": state["app"]}).json()["id"]
    q = api("GET", f"/assessments/attempts/{att}", state["stu"]).json()["sections"][0]["questions"][0]
    check("test_cases" not in json.dumps(q), "hidden tests leaked to the student")
    saved = api("PUT", f"/assessments/attempts/{att}/answers", state["stu"], json={"assessment_question_id": q["id"], "answer_text": ""}).json()
    body = {"assessment_answer_id": saved["answer_id"], "question_id": q["question"]["id"], "language": "python", "source_code": SOLUTION}
    run = api("POST", "/coding/run", state["stu"], json=body).json()
    check(all(s["passed"] for s in run["samples"]), f"sample tests failed: {run}")
    sub = api("POST", "/coding/submit", state["stu"], json=body).json()
    check(sub["result"] == "ALL_TESTS_PASSED", f"submit result: {sub}")
    api("POST", f"/assessments/attempts/{att}/submit", state["stu"])
    j = journey()
    r = stg(j, "CODING_ASSESSMENT")["round"]
    check(r["decision"] == "QUALIFIED" and r["score"] == 100.0, f"coding round: {r}")
    return "run + submit in Judge0: all tests passed, qualified"


def skip_coding_if_blocked():
    if state.get("judge0"):
        return
    api("POST", f"/hiring-pipeline/applications/{state['app']}/stages/CODING_ASSESSMENT/skip", state["stu"])
    check(stg(journey(), "TECHNICAL_INTERVIEW")["status"] == "AVAILABLE", "interview did not unlock after the optional round was skipped")


def run_interview(stage_type, answers):
    sid = state["stu"]
    itv = api("POST", "/interviews/start", sid, json={"application_id": state["app"], "stage_type": stage_type}).json()
    asked = []
    for a in answers:
        t = api("POST", f"/interviews/{itv['id']}/next-turn", sid).json()
        check(t is not None, "the interview ended earlier than planned")
        asked.append(t["question_text"])
        api("POST", f"/interviews/turns/{t['id']}/answer", sid, json={"answer_text": a, "answer_source": "text"})
    end = api("POST", f"/interviews/{itv['id']}/next-turn", sid).json()
    check(end is None, "the interview did not finish after its planned number of questions")
    check(len(set(asked)) == len(asked), "a question was repeated")
    return itv["id"], asked


def technical_interview():
    iid, asked = run_interview("TECHNICAL_INTERVIEW", [
        "A generator function uses yield to produce values lazily. Each call to next resumes it where it stopped, so large data can be streamed with little memory.",
        "Generators keep their local state between yields, which makes them good for pipelines. The trade-off is that they can be consumed only once and errors surface late.",
        "For a CPU-bound service I would use multiple processes because the GIL limits threads, and measure before optimising."])
    turns = api("GET", f"/interviews/{iid}/turns", state["coA"]).json()
    check(len(turns) == 3 and all(t["layer"] for t in turns), "turns are missing depth layers")
    check(turns[0]["layer"] == 1 and turns[1]["question_text"] != turns[0]["question_text"], "the follow-up did not adapt")
    j = journey(state["coA"])
    check(stg(j, "TECHNICAL_INTERVIEW")["status"] == "COMPLETED" and stg(j, "HR_INTERVIEW")["status"] == "AVAILABLE", "interview progression is wrong")
    return f"3 turns, layers {[t['layer'] for t in turns]}, all scored"


def hr_interview():
    iid, asked = run_interview("HR_INTERVIEW", [
        "I explain the goal first, keep updates short and check that the other person understood before moving on.",
        "In my last project we split the work by module, agreed interfaces early and reviewed each other's code.",
        "I could start within a month and I am comfortable working remotely with regular check-ins."])
    turns = api("GET", f"/interviews/{iid}/turns", state["coA"]).json()
    check(len(turns) == 3 and all(t.get("layer") is None for t in turns), "HR turns must not carry technical depth layers")
    blob = json.dumps(turns)
    check(not any(k in blob for k in ("concept_accuracy", "overall_score")), "technical scoring leaked into the HR interview")
    check(all((t.get("rubric_evaluation") or {}).get("type") == "hr_observation" for t in turns), "HR turns lack neutral observations")
    return "3 turns, neutral observations only, no technical score"


def candidate_review():
    j = journey(state["coA"])
    st = [s["status"] for s in j["stages"]]
    check(all(s in ("COMPLETED", "SKIPPED") for s in st), f"stages not all finished: {st}")
    check(j["status"].endswith("UNDER_REVIEW"), f"application status: {j['status']}")
    check(stg(j, "TECHNICAL_ASSESSMENT")["round"]["override"]["reason"].startswith(RUN), "override missing from the company's record")
    check(stg(j, "HR_INTERVIEW")["result"]["observations"], "no HR observations for the recruiter")
    sj = journey(state["stu"])
    blob = json.dumps(sj)
    check("components" not in blob and "automatic_decision" not in blob and "correct_option" not in blob, "recruiter-only fields reached the student")
    oj = journey(state["po"])
    check(all("round" not in s and "result" not in s for s in oj["stages"]), "the placement officer received scores or results")
    return "recruiter sees rounds + override + observations; student/officer views are restricted"


def proctoring_smoke():
    """Session lifecycle only, with SIMULATED device data (no real camera or microphone is involved)."""
    tok = state["stu"]
    s = api("POST", "/proctoring/sessions", tok, json={"application_id": state["app"], "kind": "ASSESSMENT"}).json()
    api("POST", f"/proctoring/sessions/{s['id']}/consent", tok)
    checks = {"camera": True, "microphone": True, "audio_signal": True, "network": True, "fullscreen_capable": True, "browser": True, "network_latency_ms": 5}
    api("POST", f"/proctoring/sessions/{s['id']}/preflight", tok, json={"passed": True, "checks": checks})
    api("POST", f"/proctoring/sessions/{s['id']}/start", tok)
    api("POST", f"/proctoring/sessions/{s['id']}/heartbeat", tok)
    api("POST", f"/proctoring/sessions/{s['id']}/complete", tok)
    return "SIMULATED DEVICE data: consent, preflight, start, heartbeat, complete"


# ------------------------------------------------------------------ summary
REQUIRED = ["API", "Valkey", "Worker", "Qdrant", "Providers"]
OPTIONAL = ["Ollama", "Judge0", "Coding"]
ORDER = ["API", "Valkey", "Worker", "Qdrant", "Providers", "Ollama", "Judge0", "Accounts", "Tenant isolation", "Job + question bank", "Pipeline setup",
         "Eligibility", "Aptitude", "Technical", "Qualification", "Coding", "Technical interview", "HR interview", "Candidate review", "Proctoring (simulated)"]


def finish(stopped=None):
    print(f"\nHireAiPro Quickfire  ({RUN})\n")
    for k in ORDER:
        s, d = results.get(k, ("NOT RUN", ""))
        print(f"  {k:<26}{s}" + (f"   {d}" if s in ("FAIL", "BLOCKED") else ""))
    fails = [k for k, (s, _) in results.items() if s == "FAIL"]
    blocked = [k for k, (s, _) in results.items() if s == "BLOCKED"]
    hard_blocked = [k for k in blocked if k not in OPTIONAL]
    if stopped or fails or hard_blocked:
        overall, code = "FAIL", 1
    elif blocked:
        overall, code = "DEGRADED", 2
    else:
        overall, code = "PASS", 0
    print(f"\n  Overall: {overall}" + (f"  (stopped at: {stopped})" if stopped else "") + (f"  (blocked: {', '.join(blocked)})" if blocked else ""))
    print("  Records are left in place under the run id; see docs/QUICKFIRE_E2E.md for cleanup.")
    sys.exit(code)


def main():
    print(f"HireAiPro quickfire {RUN} against {BASE}\n")
    t0 = time.time()
    step("API", pre_api)
    step("Valkey", pre_valkey)
    step("Worker", pre_worker)
    step("Qdrant", pre_qdrant)
    step("Providers", pre_providers)
    step("Ollama", pre_ollama, required=False)
    step("Judge0", pre_judge0, required=False)
    step("Accounts", accounts)
    step("Job + question bank", job_and_bank)
    step("Tenant isolation", isolation)
    step("Pipeline setup", configure_pipeline)
    step("Eligibility", publish_and_eligibility)
    step("Proctoring (simulated)", proctoring_smoke, required=False)
    step("Aptitude", aptitude)
    step("Technical", lambda: technical_and_override())
    results["Qualification"] = results.get("Technical", ("NOT RUN", ""))
    step("Coding", coding, required=False)
    skip_coding_if_blocked()
    step("Technical interview", technical_interview)
    step("HR interview", hr_interview)
    step("Candidate review", candidate_review)
    print(f"\nelapsed {time.time() - t0:.0f}s")
    finish()


if __name__ == "__main__":
    main()
