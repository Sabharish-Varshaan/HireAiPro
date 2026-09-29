"""Controlled interview latency trace over the real HTTP API.

Creates a fresh student, applies to N published jobs, submits a blank assessment (no model calls), then runs the AI
interview: next-turn and answer requests are timed client-side; voice turns synthesize speech with macOS `say`, upload it
to /transcribe and time STT. Run against a server started with PROCTOR_ENFORCE=false (proctoring is not what is measured).
Prints one JSON object per turn plus a summary; the password is generated here and never printed.

    PROCTOR_ENFORCE=false .venv/bin/uvicorn app.main:app --port 8021 &
    PYTHONPATH=. .venv/bin/python scripts/interview_trace.py --base http://localhost:8021/api/v1 --jobs 3 --label before
"""

import argparse
import json
import secrets
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ANSWERS = [
    "I would start from the access pattern and the constraints: what is read most often, how big the data gets and what "
    "latency matters. For lookups by key I would use a hash-based structure, for ordered or range queries a balanced tree "
    "or an index, and I would measure with realistic data before optimising further.",
    "In practice I keep changes small and reviewable, write tests first for the tricky parts, and use version control "
    "branches so that work can be merged safely. When something fails in production I reproduce it, add a regression test "
    "and only then fix it.",
    "The trade-off is between consistency and speed. I would cache read-heavy data with a sensible expiry, keep the source "
    "of truth in the database, and make writes idempotent so that retries cannot corrupt state.",
]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def summarize(name, xs):
    return {"metric": name, "n": len(xs), "p50": round(statistics.median(xs), 2), "p95": round(pct(xs, 95), 2), "max": round(max(xs), 2)} if xs else {"metric": name, "n": 0}


def speech_wav(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = Path(d) / "a.aiff", Path(d) / "a.wav"
        subprocess.run(["say", "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(wav)], check=True)
        return wav.read_bytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--label", default="run")
    ap.add_argument("--voice-every", type=int, default=2, help="every Nth turn is answered by voice (0 = never)")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=300)
    email, pw = f"trace.{int(time.time())}@example.com", secrets.token_urlsafe(18)
    r = c.post("/auth/signup", json={"email": email, "password": pw, "full_name": "Latency Trace", "role": "STUDENT"})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    jobs = c.get("/jobs", headers=h).json()
    picked = []  # (job, assessment, application_id): candidates only see an assessment after applying
    for j in jobs:
        if len(picked) >= a.jobs:
            break
        app_id = c.post("/applications", headers=h, json={"job_id": j["id"]}).json()["id"]
        det = c.get(f"/assessments/by-job/{j['id']}", headers=h)
        if det.status_code == 200 and det.json():
            picked.append((j, det.json(), app_id))
    rows, turn_no = [], 0
    for job, assessment, app_id in picked:
        att = c.post(f"/assessments/{assessment['id']}/attempts", headers=h, json={"application_id": app_id}).json()
        c.post(f"/assessments/attempts/{att['id']}/submit", headers=h).raise_for_status()
        # setup step of the redesigned client: prepare + wait for the question pool while the system check runs
        t = time.perf_counter()
        prep = c.post("/interviews/prepare", headers=h, json={"application_id": app_id})
        if prep.status_code == 200:
            while not c.get(f"/interviews/readiness/{app_id}", headers=h).json().get("ready"):
                if time.perf_counter() - t > 240:
                    break
                time.sleep(2)
        prepare_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        iv = c.post("/interviews/start", headers=h, json={"application_id": app_id})
        iv.raise_for_status()
        start_ms = (time.perf_counter() - t) * 1000
        iid = iv.json()["id"]
        for k in range(5):
            row = {"label": a.label, "job": job["title"][:40], "turn": k + 1, "start_ms": round(start_ms) if k == 0 else None,
                   "prepare_ms": round(prepare_ms) if k == 0 else None}
            t = time.perf_counter()
            resp = c.post(f"/interviews/{iid}/next-turn", headers=h)
            row["next_turn_ms"] = round((time.perf_counter() - t) * 1000)
            if resp.status_code != 200 or resp.json() is None:
                row["ended"] = resp.status_code
                rows.append(row)
                break
            turn = resp.json()
            row["question_chars"] = len(turn["question_text"])
            turn_no += 1
            voice = a.voice_every and turn_no % a.voice_every == 0
            text = ANSWERS[turn_no % len(ANSWERS)]
            if voice:
                wav = speech_wav(text)
                t = time.perf_counter()
                tr = c.post(f"/interviews/turns/{turn['id']}/transcribe", headers=h, files={"audio": ("answer.wav", wav, "audio/wav")})
                row["stt_ms"] = round((time.perf_counter() - t) * 1000)
                text = tr.json().get("text", text) if tr.status_code == 200 else text
            t = time.perf_counter()
            ans = c.post(f"/interviews/turns/{turn['id']}/answer", headers=h, json={"answer_text": text, "answer_source": "voice" if voice else "text"})
            row["answer_ms"] = round((time.perf_counter() - t) * 1000)
            row["answer_status"] = ans.status_code
            row["voice"] = bool(voice)
            row["gap_ms"] = row["answer_ms"] + row["next_turn_ms"]  # submit -> next question visible (excludes think time)
            rows.append(row)
            print(json.dumps(row), flush=True)
        c.post(f"/interviews/{iid}/finish", headers=h)
    q = [r for r in rows if "answer_ms" in r]
    text_turns = [r for r in q if not r["voice"]]
    later = [r for r in q if r["turn"] > 1]
    out = [summarize("first question after Start (next_turn_ms, turn 1)", [r["next_turn_ms"] for r in rows if r["turn"] == 1 and "answer_ms" in r]),
           summarize("next_turn_ms (all turns)", [r["next_turn_ms"] for r in q]),
           summarize("next_turn_ms (turns 2+)", [r["next_turn_ms"] for r in later]),
           summarize("answer_ms text", [r["answer_ms"] for r in text_turns]),
           summarize("answer_ms voice (after STT)", [r["answer_ms"] for r in q if r["voice"]]),
           summarize("stt_ms", [r["stt_ms"] for r in q if "stt_ms" in r]),
           summarize("gap_ms text turns (answer + next question)", [r["gap_ms"] for r in text_turns if r["turn"] < 5])]
    print("SUMMARY " + json.dumps({"label": a.label, "turns": len(q), "metrics": out}))


if __name__ == "__main__":
    main()
