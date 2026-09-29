# Interview Latency

Measured 2026-09-29 on the 16 GB M4 dev machine, over the real HTTP API, with `backend/scripts/interview_trace.py`
(3 interviews × 5 turns = **15 turns per run**, every second turn answered by **voice**: `say` → WAV → `/transcribe`).
The harness ran against a second API instance started with `PROCTOR_ENFORCE=false` (proctoring is not what is measured; no device
event was faked). Raw per-turn JSON lines: `docs/traces/`. "Gap" = the candidate presses Submit → the next question is on screen
(answer request + next-turn request; think time excluded).

## Before (agent decides everything after each answer)
Trace `interview_before.jsonl`. Flow: `next-turn` runs the Interview Agent (LLM with tools: rank, requirements, evidence, history, question
bank, RAG) inside the request; the candidate stares at "Interviewer is choosing the next question…".

| Metric (ms) | n | p50 | p95 | max |
|---|---|---|---|---|
| Question 1 after Start | 3 | 18,908 | 48,707 | 48,707 |
| Next question (`next-turn`), all turns | 15 | 16,888 | 33,633 | 48,707 |
| Answer scoring (`answer`, text) | 8 | 2,698 | 3,411 | 3,411 |
| STT (`transcribe`) | 7 | 4,262 | 5,852 | 5,852 |
| **Gap: submit → next question** (text turns) | 6 | **16,469** | 21,581 | 21,581 |

## Architecture now
1. **Authoring time** (on assessment publish, Celery `assessments.prepare_interview`; also `POST /interviews/prepare`, which the student client
   calls during the system check): `interview_templates` (competencies, importance, coverage rules, rubric version, 3–5 questions, difficulty
   range) and `interview_pool_questions` (validated questions per competency × easy/medium/hard). Sources in order: approved company/platform
   question bank, then knowledge-grounded generation (context retrieved once per skill; model calls overlap, 3 at a time). The company can review
   it at `GET /interviews/templates/by-job/{job_id}` and rebuild it.
2. **Start**: the session plan (the candidate's ranked competencies) is stored on the interview. Question 1 is a DB lookup.
3. **Each turn**: persist the answer → score it (budgeted) → deterministic selector (importance × required bonus × (1 − confidence) × 0.5^asks, difficulty from
   the last score, prerequisite probe after a weak answer) → first unseen pool question for that competency/difficulty → shown. Models are not
   asked to invent the next question. If the pool cannot serve, the previous live path runs and the turn is labelled `live_fallback`.
4. **Scoring budget**: the answer is committed first; scoring is awaited for at most `INTERVIEW_EVAL_BUDGET_SECONDS` (2.5 s) and `next-turn` gives an
   in-flight score at most `INTERVIEW_EVAL_CATCHUP_SECONDS` (1.0 s) more. A slower score finishes in the background (one row lock, recorded exactly once) and
   informs later turns. Finishing the interview waits for every unscored answer before the match is computed.
5. **Latency-sensitive scoring route**: `interview_rubric_evaluation` tries Groq first, falls back to luna (router cool-down rules unchanged). Measured on the same
   rubric: Groq p50 975 ms (4 successful calls, 0.6–1.2 s; a 5th was rate-limited), luna p50 3,863 ms (6 calls).
6. Transcription now runs in a worker thread: it used to run synchronously inside the async handler, freezing every other request (including proctoring
   heartbeats) for the full STT time.
7. Client: "✓ Answer received. Evaluating your response…" appears immediately, the next question loads automatically ("Preparing your next question…"), the
   first question loads when the interview starts, and Start stays disabled until the question pool is ready.

## After
Trace `interview_after.jsonl` (pool prepared before the candidate arrives; Groq was rate-limited during this run, so scoring used luna).

| Metric (ms) | n | p50 | p95 | max |
|---|---|---|---|---|
| Question 1 after Start | 3 | 17 | 21 | 21 |
| Next question (`next-turn`), all turns | 15 | 450 | 1,034 | 1,037 |
| Answer request (text / voice, budgeted) | 8 / 7 | 2,512 / 2,514 | 2,513 / 2,516 | 2,513 / 2,516 |
| STT (`transcribe`) | 7 | 4,436 | 5,485 | 5,485 |
| **Gap: submit → next question** (text turns) | 6 | **2,772** | 3,548 | 3,548 |

Server-side stages (`interview_turns.timing`, pool path, 27 turns in the earlier cold run): rank + select **9.5 ms p50 / 36.6 ms max**; score recalculation 20.7 ms p50;
answer scoring 2,958 ms p50 / 5,998 ms max (provider time).
Interview setup (question-pool preparation) when the job had no pool yet, measured on the trace jobs: 20.2 s, 22.2 s, 34.4 s before the Start button became active.
Authoring-time top-up of larger jobs: 17 s for 8 new questions (concurrency 3).

## What the numbers do and do not say
- **Question 1 is ready immediately** (p50 17 ms) and later questions no longer depend on a model (p50 9.5 ms selection). This part is a hard result.
- The **gap is now dominated by answer scoring**, i.e. provider latency. The 2–3 s target holds when Groq answers (0.6–1.2 s on 4 successful calls) but Groq's free
  tier returned HTTP 429 during these runs (3 of 4 interview-scoring attempts in the final run failed over), so most scoring ran on luna at ~3.0–3.9 s. With luna only, the gap is p50 2.8 s /
  p95 3.5 s; it does not go below the budget.
- With luna only, ~27% of scores (8 of 30 measured) exceed budget + catch-up (3.5 s) and are therefore not available when the next question is chosen. For those
  turns, difficulty adaptation and the weak-answer prerequisite probe apply one turn later. Evidence and the recruiter's result are unaffected (the score is recorded
  once, and finishing waits for it). Raising the budget trades latency for adaptivity.
- Scoring provider varies with availability (Groq vs luna). Both use the same rubric, but their numeric scores differ slightly (e.g. same answer: Groq 0.23–0.58,
  luna 0.49–0.67 over 6 calls each). Comparable fairness across candidates would need pinning one provider.
- Speech-to-text (faster-whisper small.en on CPU, ~4.4 s for a ~15 s clip) is unchanged; it no longer blocks other requests.
- Browser speech synthesis start latency and "next question visible" in the UI were verified in the browser E2E, not in this API trace.
- Follow-up probing (wording a question from the candidate's answer) is not implemented; adaptivity is competency + difficulty.

## Rerun
```bash
cd backend && PROCTOR_ENFORCE=false .venv/bin/uvicorn app.main:app --port 8021 &
PYTHONPATH=. .venv/bin/python scripts/interview_trace.py --base http://localhost:8021/api/v1 --jobs 3 --label mytrace
```
