# Industry Workflow Comparison

A conceptual comparison of workflow patterns commonly found in assessment and hiring products (technical screening platforms such as
CodeSignal and HackerRank, video/AI interviewing such as HireVue, proctored campus assessment such as Mercer Mettl, campus recruiting
networks such as Handshake) against HireAiPro after this pass. This is from general knowledge of those categories, not from testing those
products, and it is not a UI clone list. Priority: **P0** broken/unrealistic core, **P1** needed for a believable end-to-end product, **P2** production enhancement.

| Area | Industry pattern | HireAiPro now | Gap | Target | Priority |
|---|---|---|---|---|---|
| Assessment authoring | Blueprint (skills, counts, time), library + generated items, review, publish/version | Deterministic blueprint (target size, ~40% MCQ), bank first then generation (≤3 attempts/slot), coverage shown, delivery options, frozen version at publish | No per-type counts/weights/difficulty mix editor; no manual question editing | Recruiter-editable blueprint | P1 |
| Candidate invitation | Unique expiring link per candidate, resend, reminders | Institution invitations (hashed, single-use, expiring, resend revokes); company candidates apply themselves | No company-issued invitations to named candidates | Company invite + expiry per job | P1 |
| Preflight | Camera/mic/network/browser check before the clock | Consent, real device checks, audio level, backend round trip, fullscreen, ready gate, timer starts after | No screen-share step; no speed test beyond latency | Optional screen-share event in strict mode | P1 |
| MCQ | Navigator, mark for review, timer, shuffle | Navigator, previous/next, mark, autosave, submit confirmation, persisted question/option shuffle | No sections with separate timers | Optional timed sections | P2 |
| Coding | Visible samples + hidden tests, Run vs Submit, multi-language | 2–3 samples + 6–12 hidden (two-source verified), Run/custom input, Submit, Python/Node/C++17 in Judge0 | Hidden pass counts are not shown to candidates (a policy choice); no plagiarism check | Configurable feedback policy; plagiarism | P2 |
| Hidden tests | Never exposed to the browser | Verified in payload: samples only, hidden only as a count | — | — | done |
| Timers | Server-authoritative deadline | `started_at/expires_at/submitted_at`, server-side expiry, auto-finalize | — | — | done |
| Proctoring | Camera/screen/tab signals reviewed by humans; some add automated flags | Objective events + timeline, no automated flag by design | No screen share; no recording (by design) | Optional screen-share events | P1 |
| AI interview | Structured competency questions, fast turn-taking, rubric scoring, reviewer playback | Template + validated pool, deterministic selection, question 1 in ~0.2 s, next question 0.8–3.6 s, browser speech | No probing follow-ups; scoring provider varies with availability | Follow-up probes; pinned scoring model | P1 |
| Result visibility | Candidates see completion; employers see scores | Enforced in API DTOs and verified in the network payload | — | — | done |
| Institution onboarding | Institution admin/staff provisioning, SSO | Placement officer self-signup creates the institution | No platform approval of institutions; no staff invitations; no SSO | Admin approval + staff invites | P1/P2 |
| Staff permissions | Roles with department/cohort scoping | One staff role (Placement Officer); other roles deferred | Faculty/Department Head are institution-wide and cannot be created | Scoped staff roles | P2 (deferred) |
| Student provisioning | Roster import, invite/claim, SIS sync | CSV preview/import with row errors, single invite, resend, disable, claim with own password | No SIS sync, no bulk resend | SIS/LMS connector | P2 |
| Employer distribution | Employer requests → campus approval → eligibility → drive | Company targets an institution → officer approves with department/cohort/year eligibility → students apply | No drive scheduling, no multi-institution job, no partner directory | Partner relationships, drives | P1 |
| Reports | Cohort readiness, funnel, exports | SQL overview cards, funnel, heatmap, gaps, per-student page | No CSV export, no saved reports | Exports | P2 |

## Priorities from this comparison
**P1 next:** company-issued candidate invitations, editable blueprint, partner-institution directory, screen-share event, follow-up probing, platform approval of institutions.
**P2:** SSO, email provider, SIS sync, plagiarism detection, exports, scoped staff roles.
