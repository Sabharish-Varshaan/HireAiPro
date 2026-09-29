# Job posting

A company creates a real posting, not just a title. `backend/app/services/jobs/posting.py` is the single validator; the frontend
(`frontend/src/lib/posting.ts`) mirrors the same rules so the form and the API agree.

## Fields
| Group | Fields |
|---|---|
| Type | `employment_type`: FULL_TIME, INTERNSHIP, INTERNSHIP_TO_FULL_TIME, PART_TIME, CONTRACT (stored as identifiers; labels are display-only) |
| Where | `work_mode` (ONSITE/HYBRID/REMOTE, no default), `location_city/state/country`. City and country are required for on-site and hybrid |
| Experience | `experience_level` (fresher option, no years) or min/max years |
| Openings and deadline | `number_of_openings` (>=1), `application_deadline` (enforced by the server on apply: 409 `APPLICATIONS_CLOSED`) |
| Compensation | `compensation_currency/min/max/period/type`. Period YEAR/MONTH/HOUR/FIXED; type SALARY/STIPEND/CTC/HOURLY/UNPAID |
| Internship | `internship_duration_value/unit`, stipend (compensation with type STIPEND), `conversion_guaranteed`, `conversion_notes`, `full_time_compensation_min/max` |

## Rules
- Amounts are stored as absolute decimals. LPA is an input and display convenience only (INR + YEAR; 1 LPA = 100,000 INR/year), so there is no
  India-only column and no precision loss.
- Internship duration is required for internship types and forbidden otherwise. Conversion and full-time package fields are only valid for
  INTERNSHIP_TO_FULL_TIME. A stipend is only valid for internships. UNPAID carries no amount. A guarantee needs notes.
- Wording is "Potential full-time conversion" unless the guarantee flag is set.
- After publish only `application_deadline` and `number_of_openings` can change (`PUT /jobs/{id}/posting`, else 409).
- Publishing an assessment requires employment type, work mode, city and country (409 `POSTING_INCOMPLETE`).
- `Job.display` produces the display strings used by the company, student and placement-officer views.
- Filters: `GET /jobs?employment_type=&work_mode=`.

## Access
`GET /jobs/{id}`: students only through `student_can_access_job`; a company only for its own jobs (404 otherwise). This fixed a leak found
in the browser test, where another company could read a published job. Regression test in `tests/security/test_role_boundaries.py`.

## Tests
`tests/unit/test_job_posting.py`, `tests/integration/test_job_posting_api.py`, plus the role-boundary test.
