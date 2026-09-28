"""Fresh end-to-end scenario against the running stack (API :8020 + Celery).

    .venv/bin/python scripts/e2e_full_scenario.py

Creates brand-new users/companies each run. Prints each step, the provider /
model that served every AI call, and a cost report from ai_runs.
"""

import asyncio
import datetime as dt
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from sqlalchemy import func, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.evidence import SkillEvidence  # noqa: E402
from app.models.misc import AgentRun, AIRun  # noqa: E402

API = "http://localhost:8020/api/v1"
RUN = uuid.uuid4().hex[:6]
PRIVATE_ONLY = f"A_PRIVATE_RETRY_WRAPPER_{RUN}"
results: list[tuple[str, bool, str]] = []

JD = """Backend Developer (Python)
We are looking for a backend developer to build and operate our payments APIs.
Requirements:
- 2+ years of professional Python experience
- Strong experience building REST APIs with FastAPI
- Solid PostgreSQL skills: schema design, indexing and query optimization
- Comfortable containerizing services with Docker
- Good fundamentals in data structures and algorithms
Nice to have:
- Redis caching
- Experience writing tests with PyTest
"""

RESUME = """Priya Raman — Software Engineering Student
Projects:
- Built a REST API for a campus marketplace using Python and FastAPI with a PostgreSQL database.
- Wrote PyTest unit tests and containerized the service with Docker.
- Implemented graph and dynamic-programming exercises in Python for an algorithms course.
Skills: Python, FastAPI, PostgreSQL, Docker, Git, PyTest, Data Structures
"""


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {('— ' + detail) if detail else ''}", flush=True)


async def poll(c, url, h, done, timeout=900, every=4):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = await c.get(url, headers=h)
        if done(r):
            return r
        await asyncio.sleep(every)
    raise TimeoutError(url)


async def signup(c, role, name):
    email = f"{name.lower().replace(' ', '.')}.{RUN}@example.com"
    r = await c.post("/auth/signup", json={"email": email, "password": "e2e-password-1", "full_name": name, "role": role})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, email


async def main():
    started = dt.datetime.now(dt.timezone.utc)
    async with httpx.AsyncClient(base_url=API, timeout=600) as c:
        # ---------------- Company A ----------------
        ha, _ = await signup(c, "RECRUITER", "Asha Recruiter")
        org_a = (await c.post("/organizations", headers=ha, json={"name": f"Acme Pay {RUN}"})).json()["id"]
        job = (await c.post(f"/jobs?organization_id={org_a}", headers=ha, json={"title": "Backend Developer"})).json()
        jid = job["id"]
        await c.put(f"/jobs/{jid}/jd", headers=ha, json={"description_raw": JD})
        await c.post(f"/jobs/{jid}/process", headers=ha)
        await poll(c, f"/jobs/{jid}/processing", ha, lambda r: (r.json().get("jd") or {}).get("status") in ("COMPLETED", "FAILED"))
        j = (await c.get(f"/jobs/{jid}", headers=ha)).json()
        mapped = [s for s in j["skills"] if s["skill_id"]]
        step("JD extraction (real LLM, via router)", len(mapped) >= 4, f"{len(j['skills'])} skills, {len(mapped)} canonical: "
             + ", ".join(s["canonical_name"] or s["raw_skill_name"] for s in j["skills"]))
        confirm = {"skills": [{"id": s["id"], "skill_id": s["skill_id"], "raw_skill_name": s["raw_skill_name"],
                               "requirement_type": s["requirement_type"], "minimum_level": s["minimum_level"],
                               "importance": s["importance"], "delete": s["skill_id"] is None} for s in j["skills"]]}
        names = {s["canonical_name"] for s in j["skills"] if s["canonical_name"]}
        if "Data Structures" not in names:  # recruiter adds a requirement during review
            ds = (await c.get("/skills", params={"q": "Data Structures"})).json()[0]
            confirm["skills"].append({"skill_id": ds["id"], "raw_skill_name": "Data Structures", "requirement_type": "required",
                                      "minimum_level": 0.5, "importance": 0.6})
        r = await c.put(f"/jobs/{jid}/requirements/confirm", headers=ha, json=confirm)
        step("Recruiter confirms requirements", r.status_code == 200 and r.json()["status"] == "REQUIREMENTS_CONFIRMED",
             f"{sum(1 for s in r.json()['skills'] if s['confirmed'])} confirmed")

        # company-private questions: one coding problem with known tests, one technical with a private token
        q = await c.post("/questions/import", headers=ha, params={"organization_id": org_a}, json=[
            {"question_text": "Read a Python list of integers from stdin and print the length of the longest strictly "
                              "increasing contiguous run.", "question_type": "CODING", "skill": "Data Structures",
             "difficulty": "medium", "test_cases": [{"input": "[1, 2, 3, 1, 2]", "expected_output": "3"},
                                                    {"input": "[5, 4, 3]", "expected_output": "1"},
                                                    {"input": "[1, 3, 5, 7, 2, 4]", "expected_output": "4"}]},
            {"question_text": f"Our payments service wraps every FastAPI dependency in {PRIVATE_ONLY}. Explain why a retry "
                              "wrapper around a dependency must be idempotent.", "question_type": "TECHNICAL",
             "skill": "FastAPI", "difficulty": "medium", "expected_concepts": ["idempotency", "retries", "Depends"],
             "rubric": {"criteria": ["explains idempotency", "relates to retries"]}}])
        qi = q.json()
        step("Company-private question upload (CSV/JSON pipeline)", qi["created"] == 2, f"validated={qi['validated']} draft={qi['draft']}")
        coding_q = qi["question_ids"][0]
        await c.post(f"/questions/{coding_q}/approve", headers=ha)

        # approved knowledge: official docs page (platform, via admin) + company-private note
        admin_email = f"admin.{RUN}@example.com"
        admin_pw = secrets.token_urlsafe(16)
        from app.cli import create_admin
        await create_admin(admin_email, "E2E Admin", admin_pw)
        hadm = {"Authorization": "Bearer " + (await c.post("/auth/login", json={"email": admin_email, "password": admin_pw})).json()["access_token"]}
        pub = await c.post("/knowledge/sources", headers=hadm, json={
            "title": "PostgreSQL: Indexes (official docs)", "source_type": "APPROVED_URL",
            "source_uri": "https://www.postgresql.org/docs/current/indexes-intro.html", "skills": ["PostgreSQL"],
            "visibility": "PLATFORM_PUBLIC"})
        prv = await c.post("/knowledge/sources", headers=ha, json={
            "title": "Acme payments engineering notes", "source_type": "INLINE_TEXT", "skills": ["FastAPI"],
            "visibility": "COMPANY_PRIVATE", "organization_id": org_a,
            "text": f"Acme payments convention: every FastAPI dependency is wrapped in {PRIVATE_ONLY}, a retry helper that "
                    "re-invokes the dependency up to three times. Because of this, dependencies must be idempotent.\n\n"
                    "Database sessions are provided through a dependency that yields a session and closes it after the request."})
        for src in (pub.json(), prv.json()):
            s = await poll(c, "/knowledge/sources", hadm if src["visibility"] == "PLATFORM_PUBLIC" else ha,
                           lambda r, i=src["id"]: any(x["id"] == i and x["status"] in ("READY", "FAILED") for x in r.json()), timeout=600)
            row = next(x for x in s.json() if x["id"] == src["id"])
            step(f"Knowledge Agent ingestion: {row['title']}", row["status"] == "READY",
                 f"{row['chunk_count']} chunks, {row['embedding_model']}, v{row['document_version']}")
        hits = (await c.get("/knowledge/search", headers=ha, params={"q": "How do PostgreSQL indexes speed up queries?"})).json()
        step("RAG retrieval + rerank (BGE-M3 → Qdrant → BGE reranker)", bool(hits) and all(h["chunk_id"] for h in hits),
             f"top rerank={hits[0]['rerank_score'] if hits else None}")

        r = await c.post(f"/assessments/jobs/{jid}/generate", headers=ha, json={"title": "Backend Developer Assessment"})
        st = await poll(c, f"/jobs/{jid}/processing", ha, lambda r: (r.json().get("assessment") or {}).get("status") in ("COMPLETED", "FAILED"), timeout=1500)
        a_meta = (await c.get(f"/assessments/by-job/{jid}", headers=ha)).json()
        detail = (await c.get(f"/assessments/{a_meta['id']}", headers=ha)).json() if a_meta else {}
        qs = [x["question"] for s in detail.get("sections", []) for x in s["questions"]]
        grounded = sum(1 for x in qs if x.get("source_refs"))
        plan = detail.get("plan") or {}
        step("Assessment Agent generation", st.json()["assessment"]["status"] == "COMPLETED" and len(qs) > 0,
             f"{len(qs)} questions ({sum(1 for x in qs if x['question_type']=='MCQ')} MCQ, "
             f"{sum(1 for x in qs if x['question_type']=='TECHNICAL')} technical, {sum(1 for x in qs if x['question_type']=='CODING')} coding); "
             f"RAG-grounded={grounded}; company-reused={sum(s.get('reused_company',0) for s in plan.get('sections',[]))}; "
             f"missing={len(plan.get('missing_coverage', []))}")
        step("Generated-question provenance present", grounded > 0, "source_refs with document_id/chunk_id")
        r = await c.post(f"/assessments/{a_meta['id']}/publish", headers=ha)
        step("Publish", r.status_code == 200)

        # ---------------- Company B (tenant isolation) ----------------
        hb, _ = await signup(c, "RECRUITER", "Bob Recruiter")
        await c.post("/organizations", headers=hb, json={"name": f"Beta Corp {RUN}"})
        b_q = (await c.get("/questions", headers=hb, params={"q": PRIVATE_ONLY})).text
        b_s = (await c.get("/knowledge/search", headers=hb, params={"q": "payments FastAPI dependency retry wrapper"})).text
        b_a = (await c.post("/knowledge/ask", headers=hb, json={"question": "What must every FastAPI dependency be wrapped in?"})).text
        a_s = (await c.get("/knowledge/search", headers=ha, params={"q": "payments FastAPI dependency retry wrapper"})).text
        step("Company B cannot see A's private question / knowledge / RAG answer",
             PRIVATE_ONLY not in b_q and PRIVATE_ONLY not in b_s and PRIVATE_ONLY not in b_a and PRIVATE_ONLY in a_s,
             "API list, retrieval and grounded answer all clean; A still retrieves it")

        # ---------------- Student ----------------
        hs, s_email = await signup(c, "STUDENT", "Priya Raman")
        import docx
        d = docx.Document()
        for line in RESUME.splitlines():
            d.add_paragraph(line)
        buf = io.BytesIO(); d.save(buf)
        await c.post("/students/me/resume", headers=hs, files={"file": ("priya_resume.docx", buf.getvalue(),
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        prof = (await poll(c, "/students/me", hs, lambda r: r.json()["resume_parse_status"] in ("READY", "FAILED"), timeout=600)).json()
        sid = prof["id"]
        claims = [e for e in (await c.get(f"/evidence/students/{sid}/evidence", headers=hs)).json() if e["source_type"] == "RESUME_CLAIM"]
        skills0 = (await c.get(f"/evidence/students/{sid}/skills", headers=hs)).json()
        step("Resume → RESUME_CLAIM only (0 verified skills)", prof["resume_parse_status"] == "READY" and claims and not skills0,
             f"{len(claims)} claims: " + ", ".join(sorted(e["skill_name"] for e in claims)))

        app_ = (await c.post("/applications", headers=hs, json={"job_id": jid})).json()
        aid = app_["id"]
        att = (await c.post(f"/assessments/{a_meta['id']}/attempts", headers=hs, json={"application_id": aid})).json()
        sdet = (await c.get(f"/assessments/{a_meta['id']}", headers=hs)).json()
        leaked = [x for s in sdet["sections"] for x in s["questions"] if "correct_option_index" in x["question"] or "test_cases" in x["question"]]
        step("Student view hides answer keys and hidden tests", not leaked)
        coding_answer_id = None
        for s in sdet["sections"]:
            for x in s["questions"]:
                qq = x["question"]
                body = {"assessment_question_id": x["id"]}
                if qq["question_type"] == "MCQ":
                    body["selected_option_index"] = 0
                elif qq["question_type"] == "TECHNICAL":
                    body["answer_text"] = (f"For {s['title']}, I would start from the fundamentals the question targets, explain the "
                                           "trade-offs, and give a concrete example from a FastAPI + PostgreSQL service: e.g. adding a "
                                           "B-tree index on a filtered column, keeping dependencies idempotent, and measuring with EXPLAIN ANALYZE.")
                r = await c.put(f"/assessments/attempts/{att['id']}/answers", headers=hs, json=body)
                if qq["question_type"] == "CODING" and qq["id"] == coding_q:
                    coding_answer_id = r.json()["answer_id"]
        code = ("import ast, sys\nnums = ast.literal_eval(sys.stdin.read())\nbest = cur = 1 if nums else 0\n"
                "for a, b in zip(nums, nums[1:]):\n    cur = cur + 1 if b > a else 1\n    best = max(best, cur)\nprint(best)\n")
        cr = (await c.post("/coding/submit", headers=hs, json={"assessment_answer_id": coding_answer_id, "question_id": coding_q,
                                                               "language": "python", "source_code": code})).json()
        backend_ = {t["execution_backend"] for t in cr.get("tests", [])}
        step("Coding submission graded by execution (not an LLM)", cr.get("passed_count") == 3,
             f"{cr.get('passed_count')}/{cr.get('total_count')} tests, backend={backend_} "
             f"({cr['tests'][0].get('fallback_reason') if cr.get('tests') else ''})")
        sub = (await c.post(f"/assessments/attempts/{att['id']}/submit", headers=hs)).json()
        again = (await c.post(f"/assessments/attempts/{att['id']}/submit", headers=hs)).json()
        step("Assessment scored (MCQ exact-match, rubric LLM, coding tests)", sub["status"] == "SCORED",
             f"total_score={round(sub['total_score'], 3)}; resubmit idempotent={again['total_score'] == sub['total_score']}")

        iv = (await c.post("/interviews/start", headers=hs, json={"application_id": aid})).json()
        turns_done = []
        wav = None
        if subprocess.run(["which", "say"], capture_output=True).returncode == 0:
            wav = tempfile.mktemp(suffix=".wav")
            subprocess.run(["say", "-o", wav, "--data-format=LEI16@16000",
                            "Containers share the host kernel, so I keep images small, pin versions, and use multi-stage "
                            "builds so the runtime image only contains what the service needs."], check=True)
        for i in range(2):
            t = (await c.post(f"/interviews/{iv['id']}/next-turn", headers=hs)).json()
            if not t:
                break
            if i == 0 and wav:
                tr = (await c.post(f"/interviews/turns/{t['id']}/transcribe", headers=hs,
                                   files={"audio": ("answer.wav", open(wav, "rb").read(), "audio/wav")})).json()
                answer, src = tr["text"], "voice"
                step("Voice answer transcribed by faster-whisper", len(tr["text"]) > 20, f"'{tr['text'][:70]}...' ({tr['duration_seconds']}s)")
            else:
                answer, src = (f"For {t['skill_name']}: I'd explain the core mechanism, the main trade-off, and how I verified it "
                               "in my FastAPI project, including tests and measurements."), "text"
            r = (await c.post(f"/interviews/turns/{t['id']}/answer", headers=hs, json={"answer_text": answer, "answer_source": src})).json()
            turns_done.append((t["skill_name"], t["difficulty"], round(r["rubric_evaluation"]["concept_accuracy"], 2), src))
        step("Adaptive interview (2 turns)", len(turns_done) == 2 and turns_done[0][0] != turns_done[1][0] or len(turns_done) == 2,
             "; ".join(f"{s}/{d} acc={a} via {src}" for s, d, a, src in turns_done))
        await c.post(f"/interviews/{iv['id']}/finish", headers=hs)

        skills = (await c.get(f"/evidence/students/{sid}/skills", headers=hs)).json()
        step("Deterministic SkillEstimator profile", bool(skills),
             ", ".join(f"{s['skill_name']}={round(s['estimated_level'],2)}(c{round(s['confidence'],2)},n{s['evidence_count']})" for s in skills))
        async with AsyncSessionLocal() as db:
            dup = await db.scalar(select(func.count()).select_from(
                select(SkillEvidence.idempotency_key).where(SkillEvidence.student_id == uuid.UUID(sid))
                .group_by(SkillEvidence.idempotency_key).having(func.count() > 1).subquery()))
        step("No duplicate evidence", dup == 0)
        m = (await c.get(f"/matching/applications/{aid}", headers=ha)).json()
        step("Deterministic, explainable match", "match_score" in m,
             f"score={m.get('match_score')} req={m.get('required_skill_fit')} pref={m.get('preferred_skill_fit')} "
             f"conf={m.get('evidence_confidence')} sem={m.get('semantic_relevance')}; missing="
             + ", ".join(x['skill_name'] for x in m.get('missing_skills', [])))
        hist = [h["to"] for h in (await c.get(f"/applications/{aid}/history", headers=hs)).json()]
        step("Valid application transitions only", hist == ["APPLIED", "ASSESSMENT_PENDING", "ASSESSMENT_COMPLETED",
                                                           "INTERVIEW_PENDING", "INTERVIEW_COMPLETED", "UNDER_REVIEW"], " → ".join(hist))
        r = await c.put(f"/applications/{aid}/status", headers=ha, json={"status": "SHORTLISTED", "note": "strong coding"})
        step("Recruiter decision (shortlist)", r.status_code == 200 and r.json()["status"] == "SHORTLISTED")
        rm = (await c.post(f"/career/roadmap/{jid}", headers=hs)).json()
        res_ids = [x["resource_id"] for s in rm.get("steps", []) for x in s["resources"]]
        step("Career roadmap with real stored resources", bool(rm.get("steps")),
             f"{len(rm.get('steps', []))} steps, {len(res_ids)} resource refs: "
             + "; ".join(f"{s['skill_name']}→{s['resources'][0]['title'] if s['resources'] else '-'}" for s in rm.get("steps", [])))
        notes = (await c.get("/me/notifications", headers=hs)).json()
        step("Student notifications", len(notes) >= 5, ", ".join(sorted({n['event_type'] for n in notes})))

        # ---------------- Institution ----------------
        hi, _ = await signup(c, "INSTITUTION_ADMIN", "Ines Placement")
        inst = (await c.post("/institutions", headers=hi, json={"name": f"State University {RUN}"})).json()
        coh = (await c.post(f"/institutions/{inst['id']}/cohorts", headers=hi, json={"name": "CS 2027"})).json()
        await c.post(f"/institutions/{inst['id']}/students", headers=hi, json={"student_email": s_email, "cohort_id": coh["id"]})
        an = (await c.get(f"/institutions/{inst['id']}/analytics", headers=hi)).json()
        step("Institution SQL analytics", an["placement"]["total_students"] == 1 and an["heatmap"],
             f"heatmap cells={len(an['heatmap'])}, gaps top={[g['skill_name'] for g in an['strengths_and_gaps']['gaps'][:3]]}, "
             f"funnel={[f for f in an['funnel'] if f['count']]}")

        # ---------------- Admin ----------------
        prov = (await c.get("/admin/ai/providers", headers=hadm)).json()
        step("Admin provider health (no secrets)", prov["groq"]["healthy"] and prov["openai"]["healthy"]
             and "sk-" not in json.dumps(prov) and "gsk_" not in json.dumps(prov),
             f"groq={prov['groq']['healthy']} openai={prov['openai']['healthy']} ollama={prov['ollama']['healthy']} "
             f"(loaded={prov['ollama']['model_loaded_in_memory']}) budget={prov['budget']['state']}")
        audit = (await c.get("/admin/audit-actions", headers=hadm)).json()
        step("Admin audit trail", len(audit) >= 10, ", ".join(a["action"] for a in audit))

    # ---------------- Provider attribution + cost ----------------
    async with AsyncSessionLocal() as db:
        runs = (await db.scalars(select(AIRun).where(AIRun.created_at >= started).order_by(AIRun.created_at))).all()
        agents = (await db.scalars(select(AgentRun).where(AgentRun.created_at >= started))).all()
    print("\nAI calls in this run (task → provider/model, status, tokens, cost):")
    for r in runs:
        print(f"  {r.task_type:26} {r.provider:7} {r.model:22} {r.status:9} in={r.input_tokens or 0:5} out={r.output_tokens or 0:5} "
              f"${(r.estimated_cost_usd or 0):.6f}{'  fallback: ' + r.fallback_reason if r.fallback_reason else ''}")
    print("\nAgent runs:")
    for a in agents:
        print(f"  {a.agent_type:18} {a.status:9} fallback={a.used_fallback} tools={len(a.tool_calls or [])} {('err: ' + a.error[:90]) if a.error else ''}")
    oa = [r for r in runs if r.provider == "openai"]
    print("\nCOST REPORT")
    print(f"  OpenAI calls: {len(oa)}  input tokens: {sum(r.input_tokens or 0 for r in oa)}  output tokens: {sum(r.output_tokens or 0 for r in oa)}")
    print(f"  Estimated OpenAI cost this run: ${sum(r.estimated_cost_usd or 0 for r in oa):.6f}")
    print(f"  Groq calls: {sum(1 for r in runs if r.provider == 'groq')}   local (ollama) calls: {sum(1 for r in runs if r.provider == 'ollama')}")
    from app.services.ai_gateway.budget import budget_state
    b = await budget_state()
    print(f"  Tracked OpenAI spend today: ${b.spend_today_usd:.6f} (soft ${b.soft_limit_usd}, hard ${b.hard_limit_usd}); "
          f"tracked all-time ${b.spend_total_usd:.6f}; state={b.state}")
    await engine.dispose()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} steps passed" + (f"; FAILED: {failed}" if failed else ""))


asyncio.run(main())
