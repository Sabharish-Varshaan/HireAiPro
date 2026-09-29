# System Reality Audit

Audit date 2026-09-29, HEAD `0a71495`, clean working tree. Everything below comes from code, the dev
database and role probes, not from earlier docs. Where I could not verify something, it says so.
No code was changed for this audit. The role probe used a temporary test in the isolated test
database, which was deleted afterwards.

**Evidence labels:** `CODE` (read in source), `DB` (queried dev DB), `PROBE` (executed against the API in the test DB), `NOT MEASURED`.

## 1. Actual architecture (short)
FastAPI (`backend/app/api/v1/*`) → services → SQLAlchemy models; Celery for documents/assessment
generation/matching; Judge0 for code; AI gateway with Groq/OpenAI/Ollama; React SPA with four portals
(`frontend/src/App.tsx`: student, company, institution, admin). Tables have no invitation, token,
opportunity/campus-drive or interview-template table (`DB`: no table named `%invit%`, `%token%`,
`%opportun%`, `%drive%`, `%template%`).

## 2. Account lifecycle (the biggest gap)
| Question | Actual (`CODE` unless noted) |
|---|---|
| Who creates accounts | Anyone, via `POST /auth/signup` (`services/auth/service.py`). `SELF_SIGNUP_ROLES` = STUDENT, RECRUITER, COMPANY_ADMIN, HIRING_MANAGER, **INSTITUTION_ADMIN** |
| Platform Admin | Only `python -m app.cli create-admin` (password ≥12 chars, prompt or env). Not creatable in the UI |
| Placement Officer, Faculty, Department Head | **No code path creates these accounts.** `signup` rejects the roles, no invite exists and no admin endpoint creates users. The role probe had to insert `InstitutionMember` rows directly. `DB`: 0 such users exist |
| Password set by | The user at signup (min 8 chars). Stored as a hash (`core/security.hash_password`). No plaintext stored. Nobody else knows it |
| Email verified | No. No verification field or flow |
| Password reset | None |
| Disable account | Yes: admin `PATCH /admin/users/{id}` sets `is_active`. Login checks `is_active`, and `get_current_user` (`api/deps.py:28`) re-checks it on every request, so a disabled user's existing token stops working immediately |
| Invitations | None: no model, resend or expiry |
| Duplicate email | Signup returns 400 "Email already registered" (which reveals that the email exists) |
| JWT | HS256, `exp` = `JWT_EXPIRE_MINUTES`; no refresh or revocation |

**Institution provisioning today:** any self-signed-up INSTITUTION_ADMIN calls `POST /institutions`
and creates an institution (`api/v1/institutions.py:47`). The Platform Admin cannot create an institution or a
company; the admin pages only list them (`GET /admin/organizations`, `/admin/institutions`).
Companies are likewise self-created by any recruiter (`POST /organizations`). So *nobody approves an
institution or a company*. This is P0 for a coherent product.

## 3. Actor ownership
| Actor | Can actually create (route, table, auth) |
|---|---|
| **Platform Admin** | skills/aliases/relationships (`/admin/skills*`, `skills`), users' active flag (`PATCH /admin/users`), retry jobs, AI/usage views, platform questions (`questions.py`), knowledge sources (`knowledge.py`). **Cannot** create companies, institutions, institution admins or users |
| **Institution Admin** | own institution (self-created), departments `POST /{id}/departments`, cohorts `POST /{id}/cohorts`, **enroll an existing student account by email** `POST /{id}/students`. Nothing else: no programs, staff invite, student invite, import, drives or employer link. Analytics read |
| **Placement Officer** | `MANAGERS = (INSTITUTION_ADMIN, PLACEMENT_OFFICER)`, so identical to Institution Admin (`PROBE`: same status on every institution route). Cannot be created anyway |
| **Faculty / Department Head** | Read-only, but **institution-wide**: roster and analytics returned 200 for the whole institution (`PROBE`). `InstitutionMember.department` exists and is ignored, so there is no department or cohort scoping. They can also call the LLM summary endpoint |
| **Company / Recruiter** | organization (self, becomes COMPANY_ADMIN), jobs (`POST /jobs`), JD → requirements confirm, assessment generate/publish, private question bank, application status decisions. **No team invite**: `OrganizationMember` is written only for the creator, so a company is one person. No candidate invitation |
| **Student** | self-registers; profile, resume, applications, attempts, interviews. Can belong to one institution (`student_profiles.institution_id`, single value; enrolling into a second returns 409). Can apply without an institution. Student applies to any PUBLISHED job; no eligibility rules or targeting exist |

## 4. Workflows, traced

### 4.1 Recruiter creates job → assessment
Recruiter → `CompanyJobsPage` → `POST /jobs` (`jobs.py:44`, RECRUITER_ROLES) → `jobs`, `PUT /{id}/jd` /
`jd-file` → `POST /{id}/process` → Celery JD extraction (LLM `jd_extraction`, p50 5.2 s) → `job_skills` →
recruiter confirms `PUT /requirements/confirm` → `POST /assessments/jobs/{id}/generate` (202) →
`generate_assessment_task` → deterministic blueprint (`services/assessments/blueprint.py`, target 12
questions) + Assessment Agent (`agents/assessment_agent.py`) fills slots from question banks, else
generates (`services/assessments/generator.py`), validates (`questions/validator.py`), and verifies
coding tests with a reference solution in Judge0 (`coding_verification.py`) → `assessments`,
`assessment_sections`, `assessment_questions`, `questions`, `ai_runs`, `agent_runs`. `POST
/assessments/{id}/publish` only sets `status=PUBLISHED` and the job's status.
Recruiter cannot configure duration, section or count mix, difficulty, languages, weights, randomization,
attempts or invitation expiry. `total_duration_minutes` is written by the generator and used nowhere else.
`DB`: 14 published, 2 draft assessments.

### 4.2 Candidate attempt (real behavior)
Student → `ApplicationDetailPage` → `ProctoredGate` (system check) → `AssessmentRunner` →
`POST /assessments/{id}/attempts` (get-or-create, status IN_PROGRESS; `assessments.py:137`) →
`GET /assessments/{id}` (questions in DB order) → `PUT /attempts/{id}/answers` (autosave, row lock) →
`POST /coding/submit` (Judge0, all tests at once) → `POST /attempts/{id}/submit` → MCQ compared with the
stored key (deterministic); free-text via LLM `rubric_evaluation` (p50 2.5 s, p95 4.1 s, n=110 in `DB`);
evidence recorded → status SCORED.

| Property | Actual |
|---|---|
| Timer / server deadline | **None.** `assessment_attempts` columns are `assessment_id, application_id, student_id, status, total_score` plus timestamps (`DB`). No `started_at`/`expires_at`/`submitted_at`; nothing rejects late answers. `total_duration_minutes` is never enforced |
| Frozen version | **None.** Attempts point at the live `assessment_id`; questions are live rows, so editing after start would change a running attempt |
| Live generation at candidate time | **None in assessments.** Generation is authoring-time (Celery) |
| Randomization | None: DB `order_index` order for everyone; options in stored order |
| MCQ navigator / previous-next / mark for review | Not present (single scroll list, "Progress: n/13 answered") |
| Run vs Submit for coding | Only submit. `coding.py` always runs **all** tests (no sample/hidden split, no custom input). Hidden inputs are not sent to the browser (student gets only status and first error) |
| Attempt count | One per application (get-or-create); no retake policy |
| Written technical answers | Persisted by autosave; rubric evaluated **inside the submit request**, synchronously (not a job). Rubric comes from the stored question rubric (`expected_concepts`/`rubric`), which is good |
| Double submit | Idempotent (SCORED returns unchanged; evidence keys per answer) |

### 4.3 Coding quality (`DB`)
Test counts across all coding questions: **2 tests → 2 questions; 3 tests → 23 questions; nothing
larger.** The generator prompt literally asks for "3 test_cases" (`generator.py:195`), the validator
requires ≥2 (`validator.py:85`), and every test is scored equally. There is no visible/hidden distinction
and no test categories. Reference-solution verification against Judge0 exists and stays (`coding_verification.py`, Python reference only). Python 71,
Node 102, C++17 105 all pass the live suite (11/11, this session). Score is the pass fraction (Judge0-determined).

### 4.4 AI interview (`CODE` + `DB`)
Student `Start interview` → `POST /interviews/start` (proctor gate, needs ASSESSMENT_COMPLETED) → row only;
**no question is prepared.** "Begin interview" → `POST /{id}/next-turn` → `decide_next_turn` →
deterministic candidate ranking (`services/interviews/selector.py`) then the **LLM Interview Agent with tools**
(rank, job requirements, student evidence, history, question-bank search, RAG) which saves the turn; on agent
failure a fallback does one `generate_structured` call. This happens **in the HTTP request, while the student watches
"Interviewer is choosing the next question…"**. Answer → `POST /turns/{id}/answer` → LLM rubric evaluation
in the same request → evidence. Voice: browser records → `/transcribe` (faster-whisper) → editable text → answer.
Historical latency from `ai_runs` (`DB`; all runs, not a controlled trace):
| Stage | n | p50 | p95 |
|---|---|---|---|
| `agent:interview_agent` (next-question decision) | 30 | 6.1 s | 40.9 s |
| `interview_question` (fallback single call) | 1 | 1.4 s | — |
| `rubric_evaluation` (answer scoring) | 110 | 2.5 s | 4.1 s |
Not measured yet: per-stage breakdown (target selection, prompt build, provider), STT, TTS start, and
gap between turns over ≥10 fresh turns. `docs/INTERVIEW_LATENCY.md` will only be written from a controlled trace.
There is no interview template, no session plan, no prefetch and no question pool. Every candidate for a job
therefore gets a free-form agent path, and the recruiter cannot review the configuration.

### 4.4b Interview voice and proctoring (delivered in `0a71495`)
Browser speech and proctoring exist and were browser-verified under simulated devices. Missing versus the
requested target: optional screen-share (`getDisplayMedia`) events, and the timer starting only after the
system check (there is no timer).

### 4.5 Institution portal (`CODE`, screens read; live UI walkthrough NOT re-done in this audit)
Nav has a single item, "Analytics" (`App.tsx:65`). `InstitutionDashboard.tsx` holds: department/cohort forms,
"Enroll student" by email, filters, SQL-derived analytics cards, cohort heatmap, gaps/strengths/demand,
optional LLM summary text (`POST /analytics/summary`, described as text only) and a roster whose names now link to a per-student
review page (added in `0a71495`). Raw UUIDs appear in the student-page URL only. Missing entirely: students
list with status, pending invitations, import, programs, staff and roles, campus drives, placement pipeline,
reports, settings. Verdict: **a dashboard attached to the product, not an operating workspace.**

### 4.6 Company ↔ institution
None. No targeting of an institution, cohort or department; no approval step; no eligibility; no campus
drive; jobs are open to every student. Placement officers cannot see a candidate pipeline. The
`Application` funnel exists only as aggregate counts in analytics. (`P1` build target in section 6.)

### 4.7 Score visibility
Fixed in `245f22c`/`0a71495`: student DTOs, backend-enforced, tested (`docs/SCORE_VISIBILITY.md`).
Still open: **student `Skills` page shows bands, not levels — OK**; the recruiter decision notes are hidden. No known leak remains.

## 5. Documentation that disagrees with code
- Earlier docs and the schema imply institution "roles" (Placement Officer, Faculty, Department Head) are
  usable. In practice they cannot be created (section 2), and Faculty/Head permissions are institution-wide.
- `Assessment.total_duration_minutes` looks like a timed assessment; it is decorative.
- The proctoring doc states the timer semantics only as intent; no timer exists.

## 6. Gap register
**P0 (product not coherent)**
1. Unowned account provisioning: open self-signup as INSTITUTION_ADMIN; nobody approves institutions/companies; no invitations, password reset or email verification; staff roles unobtainable.
2. No server-authoritative timer or attempt window (`started_at/expires_at/submitted_at`); refresh/second tab semantics undefined.
3. Attempts reference mutable live assessments (no frozen version).
4. Coding tests: 2–3 per question, no visible/hidden split, no Run vs Submit.
5. Interview questions generated by an LLM agent inside the request: p50 6.1 s, p95 40.9 s dead air; first question not ready.
6. Faculty/Department Head are institution-wide; Placement Officer = Admin (permission model is nominal).

**P1**
Institution staff invitations + scoping; student import (CSV preview/errors) with claim-account invites and dev email outbox; per-attempt persisted question/option randomization; MCQ navigator (previous/next/mark-for-review); recruiter assessment blueprint (duration, counts, languages, weights, attempts, expiry); campus opportunity → institution approval → cohort/department eligibility; interview template + session plan + prefetch; screen-share proctoring event; institution IA (Students, Structure, Staff, Opportunities, Pipeline).

**P2**
SSO (`auth_provider`, `external_subject`), transactional email provider, ATS/LMS/SIS sync, plagiarism, ID verification, more languages, JWT refresh (disable is already enforced per request).

## 7. Implementation order (proposed, dependency-driven)
1. **Account foundation:** `invitations` (hashed single-use expiring tokens), `password_reset`, activation endpoints, dev email outbox; disable self-signup for INSTITUTION_ADMIN; Platform Admin creates institutions/companies (first admin by invite); institution staff invites; JWT check of `is_active`.
2. **Institution structure & scoping:** staff roles with department/cohort scope enforced in every institution query; Placement Officer vs Admin split; student import with preview and claim.
3. **Assessment integrity:** attempt `started_at/expires_at/submitted_at`, frozen assessment version snapshot, persisted randomization, blueprint configuration, MCQ navigation.
4. **Coding depth:** 8–15 tests with visible samples, hidden tests, Run vs Submit, verification by reference solution in Judge0 (multi-language), bounded replacement.
5. **Interview redesign:** template at publish, session plan, first question pre-generated in preflight, prefetch/pool, UI acknowledgement; **measure first** (10+ turn trace → `INTERVIEW_LATENCY.md`).
6. **Campus opportunities:** distribution request → officer approval → eligibility.
7. Fresh full browser E2E, auth E2E, latency E2E, docs (`FULL_DATAFLOW.md`, `PORTAL_UX_AUDIT.md`, `INDUSTRY_WORKFLOW_COMPARISON.md`).

This is several days of work at production quality; it should land as separate reviewed commits per step, not one.
