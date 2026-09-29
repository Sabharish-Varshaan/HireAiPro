# Frontend–Backend Issues

Discovered during the frontend design audit (2026-09-29).

These are **backend inconsistencies or missing behaviors** surfaced by the frontend audit.
**Do NOT fix any of these in the frontend-only redesign pass.**
They are documented here for a future backend sprint.

---

## Issue 1: Independent Student Onboarding — Empty Dashboard

**Discovered in:** `StudentDashboard.tsx`

**What happens:** A student who self-registers (not invited by a placement officer) is redirected to `/student` after signup. The API calls succeed but return empty data:
- `/students/me` → returns profile with no institution
- `/evidence/students/:id/skills` → returns []
- `/applications/mine` → returns []

**What the UI shows:** Three metric boxes showing 0/0/"Not uploaded". No institution card. No call-to-action.

**Impact:** Confusing first experience for independent students — looks broken.

**Backend consideration:** No onboarding state, no empty-state API flag. Frontend cannot safely distinguish "new student" from "student with no activity."

**Frontend workaround applied:** None (do not change backend behavior).

---

## Issue 2: `/company/questions` Nav Destination Has No Content

**Discovered in:** `CompanyQuestionsPage.tsx` (547 bytes)

**What happens:** The Company nav has "Question bank" pointing to `/company/questions`. The page currently just shows a brief note explaining that private questions are per-job.

**What's missing:** There is no cross-job question browse API exposed to the company portal at this top-level. The actual private questions are only accessible at `/company/jobs/:jobId/question-bank`.

**Impact:** The nav item appears broken — "Question bank" leads to a near-empty page.

**Backend consideration:** Would need a `/questions?organization_id=:orgId` endpoint that returns company questions independently of a specific job — this endpoint appears to exist (`GET /questions?organization_id=...`) based on the Browse component in PrivateQuestionBankPage, but CompanyQuestionsPage doesn't use it.

**Frontend workaround:** CompanyQuestionsPage will be redesigned to use the existing `/questions?organization_id=:orgId` API and render a proper question list without a job context.

---

## Issue 3: Student Job Detail Page — Minimal Implementation

**Discovered in:** `src/features/jobs/JobDetailPage.tsx` (2.6KB)

**What happens:** This file is very small — likely shows only basic job info and an Apply button. Not deeply audited due to size.

**Potential issues:**
- May display raw compensation values without formatting
- May display raw requirement levels if requirements are shown at all
- Apply button behavior not confirmed

**Backend:** No known backend issue — API likely returns full job data. This is a frontend completeness issue.

---

## Issue 4: Applications Status History — Raw Enum in History API Response

**Discovered in:** `ApplicationDetailPage.tsx` and `CandidatePage.tsx`

**What happens:** `/applications/:id/history` returns objects with `h.to` field containing raw enum strings like `ASSESSMENT_COMPLETED`, `INTERVIEW_PENDING`, `SHORTLISTED`.

**What the UI shows:** `{new Date(h.at).toLocaleString()} — ASSESSMENT_COMPLETED`

**Backend:** The API sends raw enum values. Humanization is a frontend concern — this is documented because if a future API version adds a `display_label` field, the frontend should prefer it.

**Frontend action:** Map these on the frontend — not a backend bug.

---

## Issue 5: Assessment Attempt Expiry Code

**Discovered in:** `AssessmentRunner.tsx`

**What happens:** When a save fails due to attempt expiry, the backend returns `detail.code = "ATTEMPT_EXPIRED"`. The frontend checks this specific code:
```js
if (e?.response?.data?.detail?.code === "ATTEMPT_EXPIRED")
```

**Backend contract dependency:** The frontend is tightly coupled to `ATTEMPT_EXPIRED` as a specific error code in `detail.code`. If this changes in the backend, the auto-submit on expiry will silently fail.

**Risk:** Medium — if the error code changes, expired assessments will not auto-submit and students will see a save error loop.

**Frontend action:** Document only — do not change this logic.

---

## Issue 6: Student Signup Does Not Verify Email

**Discovered in:** `docs/ACCOUNTS.md`

**What happens:** Per the docs, self-registered student accounts do not verify email ownership. Invited users prove mailbox access via token.

**Frontend implication:** No email verification UI exists or is needed — but this means the platform has no way to prevent fake account creation for open-market jobs.

**Backend consideration:** Out of scope for frontend pass.

---

*This file is updated as new issues are discovered. Last updated: 2026-09-29.*

---

## Browser validation pass (2026-09-29)

Issue 2 above is resolved on the frontend: `/company/questions` is now a real bank page (browse, add, import, filters, Company Private notice).
Nothing found in this pass required a backend change. Items worth a future backend look:

- **Legacy direct import.** The top-level `/company/questions` "Import CSV / Paste" tab still uses the older endpoint that saves immediately with no preview. The
  job-scoped question bank (`/company/jobs/:jobId/question-bank`) has the full upload, preview and confirm flow.
- **Free-text status notes.** Status history notes such as "assessment started" are stored by the backend as lowercase phrases and shown as written.
- **Reset page without a token.** `/reset-password` with no `token` shows the form; the failure only appears on submit.

## Future frontend improvements (not done in this pass)
- The Reject modal on Placement Officer opportunities and the coding question UI were not exercised in Chrome (no pending opportunity and no assessment with coding questions were available).
- Content pages cap at about 896px, which leaves empty space on very wide screens.
- Screen-reader announcements for autosave status and timer warnings.
