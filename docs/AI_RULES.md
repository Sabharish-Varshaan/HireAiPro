# AI Rules

This table is enforced in code, not just convention. Where a rule is enforced by a specific
module, it's named so a reviewer can verify it directly.

## AI MAY

| Capability | Enforced in |
|---|---|
| Extract skills from JD/resume text | `app/workers/tasks_jobs.py`, `app/workers/tasks_resumes.py` |
| Normalize extracted names against the controlled taxonomy | `app/services/skills/normalizer.py` (exact → alias → fuzzy; AI never invoked here) |
| Suggest job requirements (skills, levels, importance) | `ExtractedJobSkill` schema, always `confirmed=False` until recruiter acts |
| Generate missing assessment questions | `app/services/assessments/generator.py::generate_missing_question` |
| Validate questions structurally | `validate_question_payload` (deterministic checks; AI does not self-certify) |
| Evaluate free-text answers against an existing rubric | `app/schemas/rubric.py::RubricEvaluation`, `AIGateway.evaluate_rubric` |
| Choose the next interview competency to probe | Selection is actually deterministic (`app/services/interviews/selector.py`); AI only phrases the question |
| Explain matches and gaps in natural language | Career Agent's `summary`/`step_rationales` layered on top of deterministic gap calculation |
| Summarize institution analytics | Analytics numbers come from SQL (`app/services/analytics/institution.py`); AI is not on this path today, reserved for future summary text |

## AI MAY NOT

| Restriction | Enforced by |
|---|---|
| Create canonical skills permanently | Only `POST /admin/skills` (PLATFORM_ADMIN only) writes to `skills`; the normalizer and extraction pipelines only ever read it or write to `job_skills`/`skill_evidence`, never to `skills` itself |
| Finalize recruiter requirements | `job_skills.confirmed` defaults `False`; only `PUT /jobs/{id}/requirements/confirm` (recruiter-authenticated) sets it `True`, and assessment/matching read only confirmed rows |
| Publish global questions automatically | AI-generated questions are created `visibility=COMPANY_PRIVATE`, `status=DRAFT/VALIDATED`; only `POST /admin/questions/{id}/approve` (PLATFORM_ADMIN) can promote to `PLATFORM_PUBLIC` |
| Invent assessment criteria | Rubrics passed to the AI Gateway are built from stored `question.rubric`/`expected_concepts`, never invented at eval time |
| Judge coding correctness | `app/services/coding/judge0_client.py` — pass/fail comes only from Judge0's `status.id == 3` comparison against a stored `expected_output` |
| Directly set skill proficiency | Only `app/services/evidence/estimator.py::estimate_student_skill` (a pure deterministic function) writes to `student_skills` |
| Calculate the final match score alone | `app/services/matching/engine.py` computes `match_score` from stored `student_skills`/`job_skills` with fixed weights; no LLM call in that module |
| Invent analytics | `app/services/analytics/institution.py` uses only SQL `func.avg`/`func.count` |
| Turn resume claims into verified evidence | `BASE_WEIGHTS[RESUME_CLAIM] == 0.0` in the estimator — resume evidence is stored and shown but mathematically excluded from `estimated_level` |
| Access another tenant's private content | Every question/document/knowledge query filters by `organization_id`/`visibility`; see `search_existing_questions` |
| Change application status by itself | State transitions only happen via `PUT /applications/{id}/status`, called by an authenticated human (recruiter or student action), validated against `ALLOWED_TRANSITIONS` |

## Provider routing rules (enforced in `app/services/ai_gateway/providers.py`)

| Rule | Enforced by |
|---|---|
| Deterministic work never calls an LLM | those services don't import the gateway |
| Business code never picks a provider | only `task_type` is passed; `route()` decides |
| `gpt-6-sol` is never a default | `TASK_POLICY` has it only in `critical_complex_failure`, and only with `escalate=True` under budget (`test_h_*`) |
| Paid calls stop at the daily hard cap / reserve | `budget.budget_state()` removes OpenAI from every chain (`test_g_*`) |
| No retry storms | max 1 schema retry per provider; 429 → cool-down + immediate fallthrough (`test_d_*`) |
| Our bugs are not hidden by switching models | only transport/provider errors advance the chain (`test_j_*`) |
| Agents can't loop forever | `UsageLimits(request_limit=6)` per run |
| Remote prompts never include another tenant's content | tenant filter runs before context assembly (`docs/RAG_SECURITY.md`) |

## Proctoring and voice
- No AI judges proctoring events; there is no cheating score or accusation. Reviewers are people.
- Spoken questions are the browser's `speechSynthesis` reading the already-generated text; Replay makes
  no request and no LLM call (verified: `ai_runs` unchanged).
- Assessment slot replacement: up to `ASSESSMENT_SLOT_GENERATION_ATTEMPTS` (3) per slot, each told why the
  previous candidate was rejected; rejected fingerprints are refused; uncovered slots are reported, never faked.
