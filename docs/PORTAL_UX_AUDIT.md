# Portal UX Audit

Audited 2026-09-29 in the in-app browser after the three-role pass (Placement Officer, Company, Student; Platform Admin is internal).
"Verified" = I opened and used it in the E2E; "read" = checked in code only. States use the shared `Loading`, `Empty`, `ErrorBox`.

## Public / auth
| Page | Purpose | States | Gaps |
|---|---|---|---|
| `/login` (verified) | Sign in; wrong password → "Invalid credentials" | error ✔ | no "show password" |
| `/signup` (verified) | Student, Recruiter (company name), Placement Officer (institution name) | error ✔ | self-signup does not verify email ownership |
| `/claim?token=` (verified) | Invited person chooses own password; invalid/used/expired → one generic message | loading ✔ invalid ✔ | — |
| `/forgot-password`, `/reset-password` (verified) | Reset flow, always-the-same response | ✔ | — |
| `/dev/outbox` (verified) | Stand-in for email in development/demo; 404 in production | ✔ | unauthenticated by design in dev only |

## Placement Officer
Nav: Overview · Students · Academic structure · Opportunities · (Notifications). No pages without functionality are shown.
| Page | Primary actions | Data | States | Gaps |
|---|---|---|---|---|
| Overview (verified) | filter by department/cohort; 8 cards (active, pending, profile completion, assessed, interviewed, applications, shortlisted, offers); funnel, readiness, heatmap, gaps/demand, optional LLM summary text | SQL only | loading ✔ error ✔ | LLM summary is optional prose; readiness needs computed matches |
| Students (verified) | tabs All / Pending / Import; single invite; CSV upload → preview (row errors) → confirm; Resend, Disable, Re-enable | `student-records` | empty ✔ error ✔ | no bulk resend, no archive/search, no programs table (program is a text field) |
| Academic structure (verified) | add departments and cohorts (year) | `structure` | empty ✔ | no edit/delete, no programs |
| Opportunities (verified) | Pending/Approved/Rejected; review JD + skills; choose departments, cohorts, years; approve/reject with reason | `opportunities` | empty ✔ | approved eligibility cannot be edited; no per-job applicants view |
| Student detail (verified) | verified skills, per-application assessment score, interview status, match, proctoring timeline | `evidence`, `proctoring/review` | ✔ | no export; no reviewer notes |

## Company
Nav: Jobs · Question bank · (Notifications).
| Page | Primary actions | States | Gaps |
|---|---|---|---|
| Jobs (verified) | create job | empty ✔ | no overview or reports page; no filters |
| Job detail (verified) | JD paste/upload → AI extraction → map/confirm requirements (typeahead) → Distribution → target size, generate, delivery options, publish → coverage panel → Interview plan → candidates | loading ✔ error ✔ | unmapped-skill flow is easy to miss; the institution directory lists every institution (no partner concept) |
| Candidate (verified) | decision (shortlist/offer/reject with note), match breakdown, verified skills, evidence, assessment answers with rubric, coding results, interview turns, proctoring timeline | ✔ | long single page |
| Question bank / library (read) | company questions, import, governance | ✔ | not re-audited |

## Student
Nav: Dashboard · Jobs · Applications · Profile & resume · (Notifications). The requested "Assessments / Interviews / Skills & Career" entries are not separate pages: those flows live inside Application detail, which is a deliberate simplification.
| Page | Primary actions | States | Gaps |
|---|---|---|---|
| Jobs feed / detail (verified) | open-market and approved+eligible jobs; apply | ✔ | no reason shown for why a campus job is hidden |
| Application detail (verified) | consent → system check → timed assessment (navigator, mark, autosave, Run/Submit) → interview (spoken questions, Replay/Mute) → status and strengths | loading ✔ error ✔ | refresh requires a new system check (timer keeps running); one long page |
| Profile (verified) | headline/bio, resume upload, education/experience/projects/certifications, institution card | ✔ | — |
| Career (verified) | gaps by priority/status (no numbers), roadmap with resources | ✔ | roadmap build takes ~22 s (agent) |
| Dashboard / skill detail (read) | bands and evidence counts | ✔ | not re-audited |

## Admin (internal governance only; read)
Overview & cost, Skills, Questions, Knowledge, AI & agent runs, Background jobs, Users, Audit. The user-create and institution/company provisioning screens do not exist and are out of scope.

## Dead controls / raw ids found and fixed
Duplicate overview cards on the officer dashboard (removed); institution student page "← Roster" pointed to the dashboard (now Students); empty proctoring sessions appeared on every page load (gate no longer mounts before state loads; reviewers do not see never-consented sessions); assessment completion text referenced a non-existent menu item (corrected); badge text "NOT REQUIRED" replaced by "NOT SUBMITTED"; the old enroll-by-email form was removed. Raw UUIDs remain only in URLs.
