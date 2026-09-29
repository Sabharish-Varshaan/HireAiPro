# Company UI Audit (before this pass)

Inspected 2026-09-29 in Chrome (Claude in Chrome extension) against the running app: frontend `http://localhost:5173` (Vite; proxies `/api` to the FastAPI API
on 8020), Postgres 5435, Valkey 6380, Qdrant, Judge0 containers and a Celery worker were up. I created a fresh company through the real signup page
(`Helix Cloud Systems`) and walked: signup → Jobs → Create job → Job detail → JD extraction → Requirements → Distribution → Question bank.
Screenshots (0.6 scale) are in `docs/screens/` (`company_*_before.jpg`). Findings are recorded **before** any code change in this pass.

| # | Page | Observed | Expected | Priority | Evidence |
|---|---|---|---|---|---|
| 1 | Jobs → Create job | A single "New job title" input is the whole posting. The API and model already accept `employment_type` and `location`, but the UI never sets them; the columns are free text | A real posting: employment type, work mode, location, experience, openings, deadline, compensation, internship details | **P0** | `company_dashboard_before.jpg`; `models/jobs.py:27-28` |
| 2 | Jobs list | Rows show only the title and a status badge; no employment type, location, compensation or deadline | At-a-glance posting summary | P1 | `company_dashboard_before.jpg` |
| 3 | Job detail | No posting-details card at all; nothing shows or edits what the job actually is (type, pay, where, until when) | A "Posting details" card, editable while the job is not published | **P0** | `company_job_detail_before.jpg` |
| 4 | Job detail → Requirements | "Min level" and "Importance" are bare decimals (0.45, 0.9) with no scale or explanation | Labelled 0–1 scale or a plain-language level | P1 | `company_requirements_before.jpg` |
| 5 | Requirements | An unmapped skill ("Database schema design") shows a red note and a typeahead; workable, but the recruiter must notice it before Confirm | Keep; make the blocking reason visible at the Confirm button | P2 | `company_requirements_before.jpg` |
| 6 | Job detail → Distribution | The card shows before requirements, and the institution dropdown lists **every institution on the platform** (no partner concept, test names included) | Search-by-name / scoped list | P1 | earlier E2E + this session |
| 7 | Job detail | Confirm requirements / Publish act immediately with no summary of what will happen (publish freezes the assessment and queues institution approval) | Confirmation with consequences | P2 | observed |
| 8 | Question bank (`/company/questions`) | Global to the company, not tied to a job or assessment. Bulk import writes immediately: no preview, no validation report, no skill mapping, no duplicate check, no Excel, no downloadable template | Import as Upload → Validate → Preview → Confirm, from the job's assessment, with a generated template | **P0** | `company_question_bank_before.jpg` |
| 9 | Question bank | Raw enum labels ("TECHNICAL"), free-text skill box, no link to assessment coverage | Friendly labels; coverage view (needed / available / selected) | P1 | `company_question_bank_before.jpg` |
| 10 | Question bank | No way to reuse a question in a second job from the job page ("Browse my questions" absent) | Browse/attach from the assessment step | P1 | observed |
| 11 | Navigation | Only Jobs · Question bank · Notifications; no candidates/overview entry point outside each job | Keep (deferred); candidates stay under each job | P2 | `company_dashboard_before.jpg` |
| 12 | All pages, narrow width | Sidebar is a fixed `w-56` (224 px) with no collapse, so a 400 px phone leaves ~176 px of content. The extension's window resize did not change the viewport (stayed 1280), so this is from the CSS, not a measured overflow | Collapsible sidebar under `md` | P2 | `AppShell.tsx:49` |
| 13 | Job detail (loading states) | JD extraction and generation show status text ("Extracting… PENDING", "Generating…") | OK; no change | — | observed |
| 14 | Dead buttons / raw ids / duplicate cards | None found on the company pages inspected (the earlier duplicate cards were already fixed). "Analyze with AI" is correctly disabled until text exists | — | — | observed |

## Job-posting gaps versus the target (from #1–#3)
Present in the model: `title`, `description_raw`, `status`, `location` (free text), `employment_type` (free text, unconstrained, never set by the UI).
Missing: constrained employment type, work mode, structured location, experience range/fresher, openings, application deadline (and its server-side enforcement),
compensation (currency, range, period, type), internship duration and stipend, internship-to-full-time conversion and full-time package.
Student and Placement Officer views cannot show any of it today: `JobOut` returns only title/description/status/location/employment_type.

## Plan derived from the audit
1. Job posting model + validation (backend), Create job wizard and Posting card (frontend), student job card/detail, officer opportunity view, filters.
2. Company-private question import: template (xlsx/csv/json), batches, preview with skill mapping and duplicate detection, confirm, browse/reuse from the assessment step, coverage table, priority company → platform → AI.
3. Isolation tests, browser E2E across Company A/B, Placement Officer and Student.

## Resolution (after this pass)
| Finding | Status |
|---|---|
| 1, 3 Job posting / details card | Done: sectioned conditional form and Posting card (`docs/JOB_POSTING.md`) |
| 2 Jobs list summary | Done: type, location, compensation, deadline on each row |
| 8, 9, 10 Question bank | Done: job-scoped private bank, template, preview, confirm, Browse/attach, coverage (`docs/QUESTION_IMPORT.md`) |
| 4 Raw decimals in requirements | Not changed |
| 5, 7 Blocking reason / publish confirmation | Not changed |
| 6 Institution dropdown lists every institution | Not changed |
| 12 Sidebar not collapsible | Not changed here; a separate frontend design pass touched AppShell |
| Extra: `GET /jobs/{id}` cross-company leak | Found in the browser test and fixed |
