# Score Visibility

Hiring evaluations belong to the employer, and the enrolled institution may see them. The student sees developmental,
qualitative information only. This is enforced **at the backend** with separate student DTOs
(`app/schemas/student_views.py`). Restricted values are never serialized for a student, so DevTools
shows nothing.

## Student sees
- application status, and "Assessment completed" / "Interview completed"
- which questions were answered; coding result as a status (`ALL_TESTS_PASSED`, `SOME_TESTS_FAILED`,
  `COMPILE_OR_RUNTIME_ERROR`) plus the first error message
- interview questions and their own answers ("Answer received.")
- skill **bands** (strong / developing / emerging / not yet demonstrated), with evidence counts
- strengths / skills to develop / missing skills, and a roadmap with priority order

## Deliberate exception: round results
Where a company has configured a pass requirement for a round (`docs/ROUND_QUALIFICATION.md`), the student sees **that round's** score out of 100, the requirement and a plain
result ("Qualified for the next round" / "Round completed" / "Under review by the hiring team") through `GET /hiring-pipeline/applications/{id}`. Component breakdowns, reasons,
rubrics and the automatic-versus-override history stay company-only, and rounds without a requirement show no score. Answer-level scores are still never sent to students.

## Student never sees
Assessment and answer scores, `is_correct`, rubric values, interview difficulty and the reasoning for a question
(which embedded confidence), match/fit percentages, rank, evidence confidence and raw or normalized scores, skill
levels, test pass counts, recruiter decision notes, and proctoring review data (403).

## Who sees detailed scores
| Viewer | Access |
|---|---|
| Owning company (member of the job's organization) | full: scores, rubric, match, evidence, proctoring |
| Another company, even with its own application from the same student | 404 on the other company's application |
| Institution staff where the student is enrolled | full evaluation and proctoring, via the roster, then the student page |
| Another institution | 403 |
| Platform admin | full |

The resource-level check is `assert_can_view_application` in `app/api/tenancy.py`. A student-level check alone
let company B read company A's evaluation of a shared student; that is now fixed.

## Endpoints branching on role
`/applications/{id}`, `/assessments/attempts/by-application/{id}`, `/interviews/{id}/turns`,
`/matching/applications/{id}`, `/evidence/*`, `/career/*/gaps`, `/coding/submit` and `/me/data`. These use
`response_model=None`, so only the concrete DTO for the caller's role is serialized.

## Tests
- `tests/security/test_score_visibility.py` scans student responses recursively for restricted keys and checks
  the company A / company B / institution / other-institution matrix.
- The browser E2E fetched every student endpoint for the E2E application and found no restricted key.
