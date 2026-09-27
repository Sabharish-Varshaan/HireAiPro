# Data Flow

## JD → confirmed requirements → assessment

1. Recruiter creates a `Job`, pastes or uploads a JD (`POST /jobs`, `POST /jobs/{id}/jd-file`).
2. `POST /jobs/{id}/process` enqueues `app.workers.tasks_jobs.process_jd_task` (Celery, `documents` queue).
3. The task calls `AIGateway.extract_structured` with the `ExtractedJobSkills` schema — the LLM
   returns `raw_skill_name`, `requirement_type`, `minimum_level`, `importance`, `evidence_text`,
   `extraction_confidence` per skill.
4. Each `raw_skill_name` is normalized (`app/services/skills/normalizer.py`: exact → alias →
   fuzzy) into a canonical `skill_id`, unresolved names are kept with `skill_id=null` for the
   recruiter to fix manually.
5. Rows land in `job_skills` with `confirmed=False`; `Job.status` becomes `SKILLS_EXTRACTED`.
6. Recruiter reviews/edits in the UI and calls `PUT /jobs/{id}/requirements/confirm` — this is the
   mandatory human gate; it sets `confirmed=True` and `Job.status = REQUIREMENTS_CONFIRMED`.
7. `POST /assessments/jobs/{id}/generate` runs the Assessment Agent: deterministic blueprint →
   retrieve company-private then platform questions per skill+type → generate only what's missing
   → validate → persist `Assessment`/`AssessmentSection`/`AssessmentQuestion`.
8. `POST /assessments/{id}/publish` makes it visible to applicants; `Job.status = PUBLISHED`.

## Resume → RESUME_CLAIM evidence

1. `POST /students/me/resume` stores the file and enqueues `app.workers.tasks_resumes.process_resume_task`.
2. Text is extracted (PyMuPDF/python-docx), then `AIGateway.extract_structured` with
   `ExtractedResume` pulls named skills + a confidence per skill.
3. Each skill is normalized, and a `skill_evidence` row is written with
   `source_type=RESUME_CLAIM`. The estimator (`BASE_WEIGHTS[RESUME_CLAIM] == 0`) guarantees this
   never moves `estimated_level`.

## Assessment attempt → evidence → estimate

1. `POST /assessments/{id}/attempts` creates an `AssessmentAttempt`.
2. Answers autosave via `PUT /assessments/attempts/{id}/answers`.
3. `POST /assessments/attempts/{id}/submit`:
   - MCQ: compared against `correct_option_index` — pure equality check, no AI.
   - TECHNICAL: `AIGateway.evaluate_rubric` against the question's stored `rubric`, producing a
     `RubricEvaluation` (concept accuracy / reasoning / completeness / communication).
   - CODING: scored separately via `POST /coding/submit`, which runs the student's code through
     Judge0 against the question's stored `test_cases` — pass/fail comes only from Judge0.
   - Each scored answer writes a `skill_evidence` row, then
     `recalculate_all_skills_for_student` updates `student_skills`.

## Interview turn → evidence

1. `POST /interviews/start` creates an `Interview` tied to the application.
2. `POST /interviews/{id}/next-turn`: deterministic selector
   (`app/services/interviews/selector.py`) picks the highest-uncertainty required/preferred skill
   not yet asked `MAX_ASKS_PER_SKILL` times; the Interview Agent then phrases a question for it.
3. `POST /interviews/turns/{id}/answer` scores the answer via the same rubric mechanism as
   technical assessment questions, writes `skill_evidence` (`source_type=INTERVIEW`), and
   recalculates `student_skills`.

## Matching

`POST /matching/applications/{id}/compute` reads confirmed `job_skills` and the student's current
`student_skills`, and computes `matching_v1` (see `docs/SCORING.md`) — entirely from stored rows,
no LLM call.

## Career roadmap

`POST /career/roadmap/{job_id}` calculates gaps deterministically
(`app/services/career/gaps.py`), expands with prerequisite skills from `skill_relationships`, and
asks the AI Gateway only for the explanatory summary/rationale text — persisted as a
`LearningPath`/`LearningPathStep`.
