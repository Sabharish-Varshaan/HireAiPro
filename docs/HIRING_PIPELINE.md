# Hiring pipeline

Each job has its own ordered hiring process built from five stage types. A company turns stages on or off, orders them and configures each one; every candidate then moves through exactly the stages that job uses. Design and audit: `docs/HIRING_PIPELINE_ARCHITECTURE.md`.

| Stage (identifier) | Label | What it is | Result |
|---|---|---|---|
| `APTITUDE_ASSESSMENT` | Aptitude Assessment | Timed MCQs by category (quantitative, logical, analytical, data interpretation, verbal). No technical skill. | Score % of that attempt. No skill evidence. |
| `TECHNICAL_ASSESSMENT` | Technical Assessment | MCQ + written questions from the job's confirmed skills. Never coding. | Score %, plus skill evidence per question. |
| `CODING_ASSESSMENT` | Coding Assessment | Coding problems only: visible samples, hidden tests, Run vs Submit, Judge0. | Test-execution score, language, tests passed. |
| `TECHNICAL_INTERVIEW` | Technical Interview | Multi-turn, layered, adaptive interview over a frozen competency blueprint. | Per-competency depth and rubric evidence (feeds skill evidence and the skill match). |
| `HR_INTERVIEW` | HR Interview | Separate behavioural / logistics interview. | Neutral observations only. No score, no evidence. |

Stored values are identifiers; the UI only shows labels.

## Model
* `hiring_stages(job_id, stage_type, order_index, enabled, required, duration_minutes, question_count, proctored, status DRAFT|READY|PUBLISHED, assessment_id, config JSONB)`, unique `(job_id, stage_type)`.
* `application_stage_progress(application_id, hiring_stage_id, status LOCKED|AVAILABLE|IN_PROGRESS|COMPLETED|SKIPPED, started_at, completed_at, result_reference)`, unique per application/stage.
* Every assessment stage owns its own `Assessment` (`assessments.stage_type`), so it has its own **frozen version, timer (started/expires/submitted), attempt and shuffle layout**. Nothing is shared across stages.
* Interviews: `interviews.stage_type`, `interview_templates(job_id, stage_type)`; pool questions carry `kind`, `layer`, `category`.
* Questions: `domain` (APTITUDE | TECHNICAL | CODING | TECHNICAL_INTERVIEW | HR_INTERVIEW), `category`, `sub_category`; `skill_id` is required except for aptitude and HR.

## Configuration rules
`PUT /hiring-pipeline/jobs/{id}`: at least one stage enabled; assessments must precede interviews (reorder only inside each group), so states like "HR completed → assessment pending" cannot exist; per-type validation (category and difficulty mixes add up to 100, languages from the supported list, HR topics from the approved list, interview length limits). A published pipeline is frozen (409). `GET /hiring-pipeline/jobs/{id}` reports each stage as Disabled / Needs configuration / Preparing / Ready / Published, plus the list of things that block publishing.

Publishing (`POST .../publish`) validates every **enabled** stage only (an enabled stage with no questions, a technical interview without confirmed competencies, an HR stage without topics all block with a specific message), freezes each assessment version, prepares the interview templates and opens the job.

Legacy jobs get a default pipeline on first read: Technical Assessment + Technical Interview, exactly what they did before (`POST /assessments/{id}/publish` still works for them and refuses jobs with extra stages).

## Progression (no model involved)
`services/pipeline/service.py`. Applying creates one progress row per enabled stage: the first is AVAILABLE, the rest LOCKED. Starting an assessment attempt or an interview checks the stage server-side (`409 STAGE_LOCKED` otherwise). Completing a stage unlocks the next enabled one. `ApplicationStatus` stays as the coarse projection: first assessment started → `ASSESSMENT_PENDING`; last assessment done → `ASSESSMENT_COMPLETED`; first interview started → `INTERVIEW_PENDING`; all interviews done → `INTERVIEW_COMPLETED` → `UNDER_REVIEW`. An assessments-only pipeline ends at `UNDER_REVIEW`; an interview-only pipeline starts from `APPLIED`. Applications that predate the pipeline are backfilled from their status. **No model ever decides progression, rejection or hiring.**

## Question sources (per stage)
Company-private questions first, approved platform questions second, generation for the uncovered slots. Tenant isolation is unchanged: a company's private questions (any domain) are never read by another company's stage generation, interview pool, prompts, RAG or attach calls.
* Aptitude generation is checked twice: a structure check, then an **independent re-solve** that must pick the same option, otherwise the question is discarded.
* Technical uses the job's skills with the recruiter's MCQ share and difficulty mix (spread across skills), optionally a chosen subset of skills.
* Coding uses the existing generator and Judge0 verification; the stage's language choice narrows each frozen problem (the shared question row is untouched).

## Technical interview
* At publish, a frozen blueprint: each competency's weight %, question range, target depth and difficulty envelope. Length: the stage's duration (30/45/60 min → 6/9/10 questions) unless a count is set.
* Pool prepared before any candidate arrives: per competency **one** grounded call returns questions for five depth layers (core concept → how/why → scenario → edge/failure → trade-off), about 8 per competency. Kinds and difficulties follow the layer.
* Selection is deterministic (`services/interviews/depth.py`): strong answer → next layer, adequate → deeper until the scenario layer, weak → one diagnostic step back then move on, low evaluator confidence → one clarification; at most 4 questions per competency; coverage of the remaining competencies is protected; never a repeated question. The candidate path is a database lookup (no model wait); live generation remains a controlled fallback when no prepared question can serve.
* Turns store competency, layer, kind, difficulty, the frozen rubric version, answer, rubric evaluation and evidence. A candidate cannot finish before the configured minimum number of answers.

## HR interview
Separate template, pool, turns and result. Topics: communication, collaboration, conflict handling, motivation, career goals, work preferences, availability and logistics (built from the posting: start date, relocation, work mode, internship length). Sources: the company HR bank, a curated platform bank, posting-derived questions, optional generated ones. Every question passes `hr_safety` (protected and sensitive topics are dropped, never rephrased). Answers get neutral notes only, with sensitive content removed before storage. There is no score, personality rating, culture-fit percentage, honesty or emotion signal, HR turns create no skill evidence, and HR does not affect the match.

## Views
* **Student**: a journey (✓ Applied → stages → Final review) listing only this job's stages; one card per stage, locked ones say what unlocks them; dashboard and list name the exact next step ("Coding Assessment available", "Technical Interview ready").
* **Company**: Hiring Process tab (builder + one settings panel per stage + publish); candidate page has a stage timeline and a tab per enabled stage; per-stage analytics (`GET .../analytics`, never one blended score).
* **Placement officer**: stage names and statuses only (`Aptitude completed`, `Technical Interview pending`, ...), no questions, answer keys, rubrics, notes or scores. The opportunity card lists the hiring process.

## Proctoring
Reuses the existing session/event model: a session per stage (`kind` ASSESSMENT or INTERVIEW, labelled with the stage), consent and system check before each proctored stage, `proctored` can be turned off per stage.

## Scoring
`matching_v1` is unchanged: it depends on skill evidence, which only technical MCQ/written/coding and technical-interview answers create. Aptitude and HR add none. No cross-stage weighted total exists; each stage reports its own result. A combined score would need an explicit, recruiter-weighted, versioned `scoring_v2`; historical results stay under `scoring_v1`.

## Limitations
* Once published, a pipeline is frozen; changing it means a new job (no "new version" flow yet).
* Optional (non-required) stages exist in the model and API (`skip`), but the builder does not expose "optional".
* Platform-level aptitude and HR banks are empty apart from the curated HR questions; aptitude relies on company questions or generation.
* Aptitude and HR questions are de-duplicated by content hash only (no semantic search: they have no skill to index under).
* Interviews and assessments are proctored per stage, so each proctored stage repeats consent and the system check.
