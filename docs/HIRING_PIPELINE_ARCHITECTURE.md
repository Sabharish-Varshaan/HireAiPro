# Hiring pipeline architecture

Audit of the code at commit `3ee68d8`, then the design that reuses it. Everything in "Found" was read in the source, not assumed.

## 1. What exists today (found)

| Area | Fact (file) | Consequence |
|---|---|---|
| Job → assessment | `Assessment.job_id` (not unique); the API picks the first row per job (`assessments.py: get_assessment_for_job`, `generate` upserts one). | Several assessments per job are storable, but every reader assumes one. |
| Attempts | `AssessmentAttempt` is keyed by `(assessment_id, application_id)` and carries its own `version_id`, `started_at`, `expires_at`, `submitted_at`, shuffle layout. `start_attempt` locks the application row. | **One attempt per assessment already gives a per-stage timer and version.** |
| Versions | `AssessmentVersion` freezes content + answer keys + hidden tests at publish (`versioning.ensure_version`). | Reusable per stage as is. |
| Attempt lookup | `attempt_for_application` does `scalar(select(AssessmentAttempt).where(application_id == …))` (`assessments.py:419`). | Breaks with 2+ assessments per application; must take a stage/assessment. |
| Scoring | `_finalize` grades from the frozen version: MCQ exact match, written by rubric LLM, coding from Judge0 submissions; records `SkillEvidence` per question **using `question.skill_id`**; one `total_score`. | Aptitude has no skill, so it must not record skill evidence. Coding/technical split falls out of using separate assessments. |
| Question types | `QuestionType = MCQ / TECHNICAL / CODING`; `Question.skill_id` is **NOT NULL**; no domain/category. | Aptitude needs a domain + category and a nullable skill. |
| Blueprint | `build_blueprint` allocates mcq/technical/coding per skill by importance; problem-solving skills become coding; `_ensure_breadth` forces ~40% MCQ. | One blueprint mixes all three. Per-stage blueprints are needed. |
| Generation | `generate_assessment` (Celery) runs the Assessment Agent per job; question bank first, then platform, then generation; coding is two-source verified. | Reusable per stage with a stage-restricted blueprint. |
| Application status | `ApplicationStatus` DRAFT → APPLIED → ASSESSMENT_PENDING → ASSESSMENT_COMPLETED → INTERVIEW_PENDING → INTERVIEW_COMPLETED → UNDER_REVIEW → SHORTLISTED/OFFER/REJECTED (`state_machine.py`); transitions go through `transition_application`, which writes history, audit and a notification. | Kept as the **coarse** status. Stage progress is added beside it. No `APPLIED → INTERVIEW_PENDING`. |
| Interview | `Interview` is one per application (`interviews.py:86`); `InterviewTemplate.job_id` is **unique**; `max_turns` from the global `INTERVIEW_MAX_TURNS=5`. | Cannot hold a technical and an HR interview. |
| Interview pool | `InterviewPoolQuestion(skill, difficulty)` = 3 slots per skill (`pool.py`), `MIN_PER_SKILL=2`; generation is one LLM call per (skill, difficulty). | Too shallow for drilling; no question kind. |
| Selection | `selector.rank_candidates`: priority = importance × required bonus × (1 − confidence) × 0.5^asks; **skills with confidence ≥ 0.75 are dropped**, `MAX_ASKS_PER_SKILL=2`; difficulty follows the last score; weak answer injects a prerequisite. | Good deterministic core; the confidence exclusion and 2-ask cap make a deep interview impossible. |
| Turn scoring | `evaluate_turn_answer` + `_evaluate_and_record`: rubric → `record_evidence(INTERVIEW)` → skill recalculation; scoring is awaited at most 2.5 s, otherwise finished in the background. | Reusable for the technical interview. HR must not call `record_evidence`. |
| Match score | `matching_v1`: 0.60 required fit + 0.20 preferred + 0.15 evidence confidence + 0.05 semantic; computed from skill evidence when the interview completes. | Aptitude and HR do not touch skill evidence, so the match is unchanged. |
| Proctoring | `ProctoringSession` keyed `(application, kind)`; `require_ready_session` finds the ACTIVE session; create resumes any non-COMPLETED session; complete marks it COMPLETED. | Sequential stages work with the existing model: each stage gets its own session. Only a stage label is missing. |
| Analytics | `institution.py` counts interviewed students by any COMPLETED `Interview`. | Must count technical interviews only. |
| Frontend | One `Assessment & Interview` tab; student application page renders one assessment and one interview. | Needs a stage-aware journey. |

## 2. Design (what is reused, what is new)

### Reused unchanged
Assessment versions, attempts, timers, shuffle, autosave, Judge0 coding (samples + hidden tests + reference validation), rubric gateway, `record_evidence`/estimator, proctoring session/event model and `ProctoredGate`, tenant scoping, question import pipeline, notifications, audit.

### New tables
* `hiring_stages` — `id, job_id, stage_type, order_index, enabled, required, duration_minutes, question_count, proctored, status (DRAFT|READY|PUBLISHED), assessment_id, config JSONB`. Typed columns for what is queried; `config` holds per-type settings (category distribution, languages, competency blueprint, HR categories). Unique `(job_id, stage_type)`.
* `application_stage_progress` — `application_id, hiring_stage_id, status (LOCKED|AVAILABLE|IN_PROGRESS|COMPLETED|SKIPPED), started_at, completed_at, result_ref JSONB`. Unique `(application_id, hiring_stage_id)`.

### Changed tables
* `assessments`: + `stage_type`, `hiring_stage_id`. **One `Assessment` per assessment stage** (aptitude, technical, coding), so each gets its own version, timer and attempt.
* `questions`: + `domain` (APTITUDE | TECHNICAL | CODING | TECHNICAL_INTERVIEW | HR_INTERVIEW), `category`, `sub_category`; `skill_id` becomes nullable (required except for aptitude and HR).
* `interviews`: + `stage_type`, `hiring_stage_id`. `interview_templates`: + `stage_type`, unique `(job_id, stage_type)`. `interview_pool_questions`: + `kind`, `category`; `skill_id` nullable (HR). `interview_turns`: + `category`, `layer`; `target_skill_id` nullable.
* `proctoring_sessions`: + `hiring_stage_id` (label only).

### Deterministic progression (no LLM)
`services/pipeline`:
* `init_progress(application)` creates a row per **enabled** stage; the first is AVAILABLE, the rest LOCKED. A disabled stage never gets a row, so it never appears as missing.
* `complete_stage(application, stage, ref)` marks COMPLETED and makes the next enabled stage AVAILABLE. When nothing is left the application moves to UNDER_REVIEW.
* The coarse `ApplicationStatus` is a projection: first assessment stage started → ASSESSMENT_PENDING; last assessment stage done → ASSESSMENT_COMPLETED; first interview started → INTERVIEW_PENDING; last interview done → INTERVIEW_COMPLETED → UNDER_REVIEW. One transition is added, `APPLIED → INTERVIEW_PENDING`, for pipelines without assessment stages.
* Order is constrained: assessment stages come before interview stages; stages can be reordered inside each group. This prevents "HR completed → assessment pending".
* Start endpoints refuse a LOCKED stage (409 `STAGE_LOCKED`).
* The AI never rejects or hires; recruiter decisions stay with humans.

### Legacy compatibility
A job without a pipeline gets a default one on first read: `TECHNICAL_ASSESSMENT` (its existing single mixed assessment) → `TECHNICAL_INTERVIEW` (its existing template). The 200+ existing tests and published jobs behave as before.

### Scoring (`scoring_v1` stays)
No cross-stage weighted total is invented. Each stage reports its own result (aptitude %, technical %, coding %, interview evidence, HR observations). The existing `matching_v1` match is untouched because it derives only from skill evidence. If a weighted total is wanted later it needs an explicit, versioned `scoring_v2` with recruiter-set weights; historical rows stay `scoring_v1`.

### Technical interview
* Frozen blueprint at publish: competencies with weight %, question range, target depth, difficulty envelope, rubric version (stored in the template config and copied into `Interview.plan` at start).
* Pool: per competency, one structured LLM call returns 6–10 questions tagged `(kind, difficulty, layer)`; kinds `conceptual | scenario | debugging | tradeoff`. Prepared at publish; the candidate path is a database lookup.
* Selector (`services/interviews/depth.py`): keeps the importance-based ranking but (a) does not drop already-known competencies, (b) allows up to 4 asks per competency, (c) picks the next layer by evidence: strong → next layer/harder, weak → easier/diagnostic, low evaluator confidence → clarification, (d) stops when the configured turns/minutes are reached and every required competency is covered.
* Live generation stays only as the existing controlled fallback.

### HR interview
Separate stage, separate template/pool/turns. Categories: communication, collaboration, conflict handling, motivation, career goals, work preferences, availability/notice/relocation/work-mode. Sources: company HR bank, curated platform pool, optional role-contextualised generation behind a sensitive-topic filter. Answers get structured, non-numeric observations only; **no skill evidence, no score, no pseudo-scientific metrics, no emotion or honesty inference**.

## 3. Build order
1 model + migration → 2 progression service → 3 stage assessments (aptitude/technical/coding) → 4 deep technical interview → 5 HR interview → 6 company UI → 7 student UI → 8 candidate/officer views → 9 tests → 10 Chrome E2E → 11 regression → 12 docs → commit.
