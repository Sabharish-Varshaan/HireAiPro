# Round qualification and demand-based agents

## Rule
`round_score >= pass_threshold` → **Qualified**, otherwise **Not qualified**. Scale 0–100. A score exactly at the threshold qualifies. The rule lives in
`app/services/pipeline/qualification.py` (`decide`) and is the only thing that moves a candidate on; no model is asked whether to advance.

## Configuration (per job and round)
Company → Job → **Hiring Process** → select a round → **Qualification**: pass threshold (0–100), "Automatically qualify candidates who meet this score",
component weights where the round has components, and the next round. The HR interview has no score, so no threshold.
* No threshold: the round only completes and the next one opens (previous behaviour).
* Threshold + automatic ON: qualified / not qualified as above.
* Threshold + automatic OFF: the result is *manual review*; a person advances the candidate.
Validation (server side): threshold finite and within 0–100; automatic qualification needs a threshold; weights are non-negative, only for the round's own
components and add to 100. Settings are editable after publishing (`PUT /hiring-pipeline/jobs/{id}/qualification`), content is not.

## Score composition
| Round | Components (weights are the company's; defaults only where noted) |
|---|---|
| Aptitude | single result |
| Technical assessment | multiple choice, written |
| Coding | coding |
| Technical interview | accuracy, reasoning, completeness, communication (default 40/25/25/10, the existing interview rubric) |
| HR interview | none (notes only) |
Each component is normalised to 0–100 before weighting. With no weights, an assessment uses its own points-weighted total. A weighted component that has no
score makes the round unscorable: **manual review, never a misleading number**.

## States and edge cases
`QUALIFIED`, `NOT_QUALIFIED`, `MANUAL_REVIEW`, `EVALUATION_PENDING` (shown to people as Qualified / Not qualified / Manual review / Evaluating).
* Evaluation still running, or a scoring provider failed → `EVALUATION_PENDING`: no decision, next round stays locked, the candidate is not sent to review and
  nothing counts as a failure. When the late score arrives (or a company clicks re-evaluate) the decision is computed.
* Assessment expiry keeps the existing `ATTEMPT_EXPIRED` behaviour; the attempt is finalised from what was saved.
* Not qualified / manual review mid-pipeline: the next round stays **locked on the server** (`409 STAGE_LOCKED`) and the application moves to *under review*.

## Persistence and reproducibility
`round_results`: application, round, evaluation version, score, threshold **in force when evaluated**, decision, machine reason, score components with weights,
engine version, evaluated-at. Changing a threshold later never rewrites earlier results; `POST .../stages/{round}/evaluate` is an explicit, audited
re-evaluation that adds a new version (old ones are kept).

## Manual override
`POST /hiring-pipeline/applications/{id}/stages/{round}/override` (recruiter roles): advance despite the score, or hold. A reason (≥ 5 characters) is
required. Score, threshold and the automatic decision are never edited; the override, actor, time and previous decision are stored on the result and audited
(`round_override`). Advancing unlocks the next round; holding is refused once the next round has started.

## What each audience sees
* Student: after a round with a requirement, `74 / 100`, requirement `70 / 100`, "Qualified for the next round" and the next round's name, or "Round completed".
  No components, reasons, rubric or agent output. (This is the only place a student sees a number; answer-level scores stay hidden.)
* Company: round timeline in Candidate → Status & Decision (score, requirement, result, time, component breakdown, override history).
* Placement officer: stage names and statuses only.

## Demand-based agents (`app/agents/orchestrator.py`)
A registry of the components that exist (deterministic MCQ checker, coding evaluator, interview depth planner, matching and qualification engines, audio
transcriber, resume evidence agent, assessment/interview evaluators, HR observer, interview/assessment/career/knowledge agents), each with capabilities,
cost/latency class, and the router task type that the existing cost-aware provider router maps to models (no model names are fixed in code).
`plan_task(task, **facts)` resolves the capabilities the request actually needs and picks the cheapest component that provides each; the rest are listed as
skipped. Hard caps travel with the plan (steps, model calls, seconds); timeouts, retries and fallback stay with the router.

| Task | Agents selected | Model path | Skipped |
|---|---|---|---|
| MCQ scoring | mcq_checker | none (deterministic) | evaluators, coding, audio, interview agents |
| Written answer | assessment_evaluator (+ mcq_checker if MCQs) | router task `rubric_evaluation` | coding, audio, resume |
| Coding | coding_evaluator | none (test results) | all model-backed agents |
| Resume screening | resume_evidence_agent, matching_engine | router task `resume_extraction`; matching deterministic | audio, coding, interview |
| Interview next question | depth_planner (pool ready) / hr_selector | none | interview_agent (only the controlled fallback when the pool cannot serve) |
| Interview answer | interview_evaluator or hr_observer (+ audio_transcriber for voice) | router `interview_rubric_evaluation` / `hr_observation` | everything else |
| Qualification | qualification_engine | none | all |
Assessment and interview scoring run on these plans; evaluators receive a compact job context (role, required/preferred skills, experience, current round,
rubric) and nothing about the candidate beyond the answer. A compact trace (task, agents, capability, router task type, status, latency, skipped) is stored
in `agent_runs`; no reasoning text is stored.
