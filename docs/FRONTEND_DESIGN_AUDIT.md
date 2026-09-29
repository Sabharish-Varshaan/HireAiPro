# HireAiPro — Frontend Design Audit

**Audit date:** 2026-09-29
**App URL confirmed:** http://localhost:5173 (Vite dev server, port 5173)
**Stack:** React 19, Vite 8, Tailwind CSS v4, TanStack Query v5, React Router v7
**Roles inspected:** Student, Company/Recruiter, Placement Officer

---

## 1. Method

All source files read directly. App opened in Chrome at localhost:5173. Auth pages (login, signup, claim) visually confirmed. Authenticated pages audited via source code because no test credentials were available for automated login in the browser subagent. Backend is running (API proxied to port 8020). Refer to `docs/ACCOUNTS.md` for account creation.

---

## 2. Current Technology Reality

| Layer | Current state |
|---|---|
| CSS framework | Tailwind CSS v4 via `@tailwindcss/vite` (no config file, CSS-first approach) |
| Design tokens | Barely any — mostly ad-hoc Tailwind classes scattered across files |
| Shared components | `components/ui.tsx` — Loading, Empty, ErrorBox, Badge, Card, Button, Table + helpers |
| Icons | None — emoji used in a few places (🔊, 🎙, ■) |
| Typography | System font stack — no Google Fonts |
| Color system | No semantic tokens — raw `gray-900`, `gray-500`, `red-600` throughout |
| Layout | Single shared AppShell (sidebar + main outlet), no top bar |
| Responsive | `min-w-0` on main, `max-w-3xl/4xl/5xl/6xl` per page — no systematic breakpoints |
| Animation | None |
| Loading states | Text: "Loading…" paragraph — no skeletons |
| Empty states | Text: "No data" paragraphs — no illustrations or CTAs |
| Error states | ErrorBox component — minimal red box |

---

## 3. App Shell Audit (Shared)

**File:** `src/components/AppShell.tsx`

### Current layout
```
[Sidebar 224px fixed] | [Main: flex-1, p-6]
```
- Logo area: text "HireAiPro" + raw role name (COMPANY_ADMIN, PLACEMENT_OFFICER, etc.)
- Nav: plain NavLink with active = bg-gray-100 highlight
- Notifications bell: lives inside the nav list between nav links
- User info: bottom of sidebar, shows fullName + red "Sign out" underline link
- No top bar, no breadcrumbs, no page header pattern

### Issues

| Issue | Priority |
|---|---|
| Raw enum role label displayed (COMPANY_ADMIN, PLACEMENT_OFFICER) | P0 |
| Notification bell is inside the nav list between nav links — confusing | P1 |
| No top bar — no consistent area for user menu, global actions, role indicator | P1 |
| Sidebar shows 0 icons — hard to scan quickly | P2 |
| "Sign out" styled as red underline link — weak affordance | P2 |
| Sidebar has no collapse mechanism | P2 |
| HireAiPro logo text has no weight/styling — looks like body text | P2 |
| No page header component — each page uses ad-hoc h1 | P2 |
| No section header pattern | P2 |

### Navigation per role

**Student nav (current):** Dashboard / Jobs / Applications / Profile & resume
- Skills/Career accessible but NOT in nav (only linked from Application Detail)

**Company nav (current):** Jobs / Question bank
- `/company/questions` is near-empty — just a redirect notice
- Candidates only accessible from job detail link
- No top-level Candidates view

**Institution nav (current):** Overview / Students / Academic structure / Opportunities

---

## 4. Authentication Pages

### Login Page (`/login`)

**Current visual:** White card on gray-50, centered. "Sign in" h1, email/password inputs, sign-in button. Error inline.

| Issue | Priority |
|---|---|
| No label elements — inputs use only placeholders (accessibility) | P1 |
| No autocomplete attributes on inputs | P2 |
| No keyboard focus ring styling beyond browser default | P2 |
| No logo/brand above the form | P2 |
| Forgot password + Sign up crammed in one line with dot separator | P2 |

### Signup Page (`/signup`)

| Issue | Priority |
|---|---|
| Role select shows raw internal labels (Recruiter, Placement Officer) | P1 |
| No label elements — inputs use only placeholders | P1 |
| After student signup → /student but API errors if not in institution — poor onboarding | P1 |
| Helper text "Invited by your institution?" visually buried | P2 |

### Claim Account (`/claim`)

| Issue | Priority |
|---|---|
| Error state ("Invitation not valid") — message is good but UI is cold/blank | P2 |
| No visual relationship to platform branding | P2 |

---

## 5. Student Portal

### 5.1 Dashboard (`/student`)

**Current state:** Three metric boxes (Resume status, Applications, Verified skills) in 3-col grid. Verified skills list with Band badges. Two underline links.

| Issue | Priority |
|---|---|
| Resume status shows raw backend enum: PENDING, PROCESSING, PARSED, FAILED | P0 |
| Heading is "Your profile" but it is the dashboard — misleading | P1 |
| No welcome message or user name | P1 |
| Three metrics have no visual weight — plain text on light gray | P1 |
| "Browse jobs" and "My applications" are underline-only text links — poor CTA | P1 |
| No summary of active applications or pending assessments | P1 |
| Empty state is text-only — no illustration or actionable prompt | P2 |
| No loading skeleton | P2 |

### 5.2 Jobs Feed (`/student/jobs`)

**Current state:** Filter chips (Type, Work mode). Job cards: title, org name, JobFacts compact. Link to job detail.

| Issue | Priority |
|---|---|
| No search by title/keyword | P1 |
| Job card has no compensation display | P1 |
| Job card has no deadline display | P1 |
| Job card has no "Already applied" indicator | P1 |
| No results count | P2 |
| No loading skeleton | P2 |
| Filter chip label area is w-20 fixed width — awkward | P2 |

### 5.3 Application Detail (`/student/applications/:applicationId`)

**Current state:** Back link, h1 with job title and status badge. Progress card (history list). Assessment card (inline AssessmentRunner). Interview card (inline InterviewRunner + ProctoredGate). Strengths/skills card.

| Issue | Priority |
|---|---|
| Status badge shows raw enum: APPLIED, ASSESSMENT_PENDING, ASSESSMENT_COMPLETED, etc. | P0 |
| History list shows raw enum names for status transitions | P0 |
| Progress section is a raw ol with timestamps — no visual timeline | P1 |
| Assessment and Interview embedded inline — not focused layout | P1 |
| No clear separation between completed and pending sections | P2 |
| "Build my learning roadmap →" link is underline-only | P2 |

### 5.4 Assessment Runner (in ApplicationDetailPage)

**Current state:** Sticky top bar (answered/marked counts + timer). Navigator (8×8 square buttons). Question area. Prev/Next/Mark for Review. Submit confirmation.

| Issue | Priority |
|---|---|
| Assessment runs inside main layout with sidebar visible — not distraction-free | P0 |
| Timer small and in same row as answered count | P1 |
| Navigator buttons w-8 h-8 — tight with many questions | P1 |
| Navigator legend text is 11px — easy to miss | P2 |
| MCQ options use unstyled browser radio inputs | P2 |
| TECHNICAL type: plain textarea with no character count | P2 |
| Question type shown as raw MCQ/TECHNICAL/CODING | P2 |
| Completed state shows raw answer list with question_type badges | P1 |

### 5.5 Coding Assessment (`CodingQuestion.tsx`)

| Issue | Priority |
|---|---|
| Monaco editor runs inside sidebar layout — full width not available | P0 |
| Run vs Submit visual differentiation needs confirmation | P1 |
| Language selector needs to be visible and prominent | P1 |

### 5.6 AI Interview (`InterviewRunner.tsx`)

**Current state:** Each turn is a bordered box. Voice controls inline. Recording button. Textarea for answer. Submit answer button.

| Issue | Priority |
|---|---|
| All turns listed vertically — previous questions pile up creating long scroll | P1 |
| "Transcribing with faster-whisper…" — exposes backend implementation detail | P1 |
| No progress indicator (Question 2 of ~6) | P1 |
| Transcript metadata shown: "Transcribed 4s (whisper-base, en)" — too detailed | P2 |
| Voice controls use emoji buttons (🔊) — looks informal | P2 |
| "■ Stop recording" uses danger variant — looks like an error | P2 |

### 5.7 Profile (`/student/profile`)

**Current state:** Institution card. About card (headline/bio/location). Resume card. Education/Experience/Projects/Certifications tables + add forms.

| Issue | Priority |
|---|---|
| Resume badge shows raw enum: PENDING, PROCESSING, PARSED, FAILED | P0 |
| Add forms are inline below each section — no clear add entry visual | P1 |
| AddForm fields all w-40 width in a flex row — cramped | P1 |
| No delete functionality for education, experience, projects, certifications | P1 |
| Skills claims: each Badge has "· claim" suffix — awkward | P2 |

---

## 6. Company Portal

### 6.1 Jobs List (`/company`)

**Current state:** Page header "OrgName — Jobs". "New job posting" button. Create job inline card. Jobs list (link cards with status badge).

| Issue | Priority |
|---|---|
| Status badge in jobs list: DRAFT, CLOSED are raw (others partially humanized) | P1 |
| Inline job creation form above list — creates context confusion | P1 |
| Helper text below create form is a dense paragraph | P2 |
| Page title includes "— Jobs" suffix redundant with nav label | P2 |

### 6.2 Job Detail (`/company/jobs/:jobId`) — most complex page (430 lines)

Contains: JD input/analysis, PostingCard, DistributionCard, RequirementsEditor, AssessmentPanel, InterviewPlanCard, Candidates table — all stacked vertically.

| Issue | Priority |
|---|---|
| Raw job status badge at top (DRAFT, SKILLS_EXTRACTED, REQUIREMENTS_CONFIRMED, ASSESSMENT_READY, PUBLISHED) | P0 |
| Requirements table: "Min level" and "Importance" are raw 0.0–1.0 decimal inputs | P0 |
| Requirements card badge shows raw REQUIREMENTS_CONFIRMED | P0 |
| DistributionCard badge shows raw OPEN MARKET and NOT SUBMITTED | P0 |
| Assessment card badge shows raw PUBLISHED, DRAFT etc. | P0 |
| Interview plan competency Importance column is raw decimal | P0 |
| Candidates table status badge shows raw enums | P0 |
| Question table: source_type, status, question_type all raw backend values | P1 |
| Provenance column shows truncated chunk IDs — irrelevant to recruiter | P1 |
| "Analyzing…" state shows: "Extracting requirements… (RUNNING)" — raw status | P1 |
| "Generating (Assessment Agent)…" — exposes implementation detail | P1 |
| Private bank link is a tiny underline link buried inside assessment card | P1 |
| Entire page is one long scroll with no navigation — very long for published job | P1 |

### 6.3 Private Question Bank (`/company/jobs/:jobId/question-bank`)

**Current state:** Coverage card (table). Add Question (inline form). Import Questions card. Browse card.

| Issue | Priority |
|---|---|
| Import card: template download buttons not visually prioritized | P1 |
| Import preview table very wide — raw "in company_bank (row 3)" duplicate text | P1 |
| No per-question delete | P1 |
| Coverage table has internal column labels: "Platform (approved)", "Selected" | P2 |
| Add Question form opens inline below button — no modal/drawer | P2 |

### 6.4 Candidate Page (`/company/applications/:applicationId`)

**Current state:** Name + status badge. Decision card. Match explanation. Skill profile. Evidence. Assessment. Proctoring. Interview turns.

| Issue | Priority |
|---|---|
| Status badge shows raw enum | P0 |
| Decision card is the FIRST card — above all analysis | P1 |
| Skill profile table shows internal scoring_version string | P1 |
| Evidence table: source_type shows raw RESUME_CLAIM, ASSESSMENT_MCQ, etc. | P1 |
| Interview turns: skill_name, difficulty, answer_source raw | P1 |
| History log: raw enums in status transitions | P1 |
| All content is one very long scroll — no tabs or sections | P1 |
| "deterministic formula, no LLM" — internal implementation detail | P2 |

### 6.5 Company Questions Page (`/company/questions`)

| Issue | Priority |
|---|---|
| Primary nav item leads to near-empty page — only a redirect notice | P0 |
| Nav label "Question bank" but page doesn't show any questions | P0 |

---

## 7. Placement Officer Portal

### 7.1 Overview / Dashboard (`/institution`)

**Current state:** Institution name header with filter dropdowns. 8-metric card grid. Analytics: readiness, assessment performance, funnel, heatmap, gaps, strengths, industry demand, AI summary, student roster.

| Issue | Priority |
|---|---|
| 8 metric cards in 4-col grid — overwhelming, no visual hierarchy | P1 |
| Dashboard AND student roster on same page — too much content | P1 |
| "Role readiness (from stored matching_v1 scores)" — exposes internal version | P1 |
| Filter dropdowns at right of h1 — odd placement | P2 |
| AI Summary card shows model name (generated_by) in text | P2 |
| Analytics section has no skeleton while loading | P2 |

### 7.2 Students (`/institution/students`)

**Current state:** Tab bar (All / Pending / Import). Invite single student form. Student list table.

| Issue | Priority |
|---|---|
| Invite form always visible above list when tab = ALL — wastes space | P1 |
| Invite form uses 8 inputs in grid-cols-4 — very dense | P1 |
| Status badge ACTIVE not humanized (stays "ACTIVE") | P1 |
| Import column spec shown verbatim to user | P2 |
| "Active X · Pending Y · Disabled Z" summary hard to scan | P2 |

### 7.3 Opportunities (`/institution/opportunities`)

**Current state:** Tabs (Pending / Approved / Rejected). Employment type + work mode filters. Each opportunity as a full Review card.

| Issue | Priority |
|---|---|
| Reject input inline next to button — awkward for data entry | P1 |
| Many opportunities = wall of full-height cards | P1 |
| No count badges on tabs | P2 |
| Graduation years: comma-separated string input — bare | P2 |

---

## 8. Shared Component Issues

### Badge
- Maps status → tone correctly for most cases
- Does replaceAll("_", " ") on string — good
- STATUS_TONE map has good coverage
- Very long enum names still appear after humanization (e.g. "REQUIREMENTS CONFIRMED")

### Button
- Three variants: primary (black/bg-gray-900), secondary (white/border), danger (red border)
- No icon support
- Loading state is caller's responsibility — inconsistent UX

### Table
- No sortable columns
- No row hover state
- No pagination
- No sticky headers

### Loading
- Plain `<p className="text-sm text-gray-500">Loading…</p>`
- No spinner, no skeleton

### Empty
- Plain `<p className="text-sm text-gray-500">{children}</p>`
- No illustration, no CTA

### ErrorBox
- Good functional design — human error message + optional Retry button

---

## 9. Summary of P0 Issues (Immediate Priority)

1. Raw role enum in sidebar: COMPANY_ADMIN, PLACEMENT_OFFICER, etc.
2. Raw status enums on badges across all portals (dozens of instances)
3. Resume parse status raw enum on student dashboard and profile
4. Requirements editor: Min level and Importance are raw 0.0–1.0 decimal inputs with no humanization
5. Job status badge on company job detail: raw enum
6. Assessment status badge on company job detail: raw enum
7. Candidates table status badge: raw enum
8. Interview plan competency Importance: raw decimal
9. `/company/questions` nav item leads to near-empty page
10. Assessment runner: sidebar visible during test — not distraction-free
11. Coding editor: sidebar layout limits Monaco width

---

## 10. Proposed Design System

### Typography

```
Font: Inter (Google Fonts CDN — add to index.html)

Scale:
  page-title:    28px / 700 / letter-spacing -0.02em
  section-title: 20px / 600 / letter-spacing -0.01em
  card-title:    14px / 600
  body:          14px / 400
  secondary:     13px / 400
  caption:       12px / 400
  metric:        32px / 700 / tabular-nums
  mono:          13px / Monaco, Menlo (timer, codes)
```

### Color Semantic Tokens (CSS custom properties)

```css
:root {
  /* Backgrounds */
  --bg: #F8F9FB;
  --surface: #FFFFFF;
  --surface-muted: #F2F4F7;

  /* Text */
  --text-primary: #0F1729;
  --text-secondary: #4B5563;
  --text-muted: #9CA3AF;

  /* Borders */
  --border: #E5E7EB;
  --border-strong: #D1D5DB;
  --border-focus: #3B82F6;

  /* Brand */
  --primary: #1D4ED8;
  --primary-hover: #1E40AF;
  --primary-subtle: #EFF6FF;

  /* Status */
  --success: #059669;
  --success-surface: #ECFDF5;
  --success-border: #A7F3D0;
  --warning: #D97706;
  --warning-surface: #FFFBEB;
  --warning-border: #FDE68A;
  --danger: #DC2626;
  --danger-surface: #FEF2F2;
  --danger-border: #FECACA;
  --info: #2563EB;
  --info-surface: #EFF6FF;
  --info-border: #BFDBFE;
  --neutral: #6B7280;
  --neutral-surface: #F9FAFB;
  --neutral-border: #E5E7EB;
}
```

### Layout Constants

```
Sidebar width:               220px
Content max-width (student): 800px
Content max-width (company): 960px
Content max-width (institution): 1200px
Top bar height:              56px
Border radius sm:            4px
Border radius md:            6px
Border radius lg:            10px
```

### Sidebar Nav Design

```
Active:  background = primary-subtle, text = primary, 2px left border in primary
Hover:   background = surface-muted
Label:   13px / 500
Icons:   16×16 stroke (Heroicons or Lucide)
Bottom:  user name + role pill + sign out (not red text)
```

### Status Badge Humanization Map (frontend display only)

```
DRAFT                   → Draft
SKILLS_EXTRACTED        → Requirements extracted
REQUIREMENTS_CONFIRMED  → Requirements confirmed
ASSESSMENT_READY        → Ready for assessment
PUBLISHED               → Published
CLOSED                  → Closed

APPLIED                 → Applied
ASSESSMENT_PENDING      → Assessment pending
ASSESSMENT_COMPLETED    → Assessment done
INTERVIEW_PENDING       → Interview pending
INTERVIEW_COMPLETED     → Interview done
UNDER_REVIEW            → Under review
SHORTLISTED             → Shortlisted
OFFER                   → Offer made
REJECTED                → Not selected

PENDING                 → Pending
ACTIVE                  → Active
DISABLED                → Disabled

PARSED                  → Processed
PROCESSING              → Processing
FAILED                  → Failed

COMPANY_ADMIN           → Company Admin
RECRUITER               → Recruiter
PLACEMENT_OFFICER       → Placement Officer
STUDENT                 → Student
PLATFORM_ADMIN          → Platform Admin
INSTITUTION_ADMIN       → Institution Admin
```

### Requirements Humanization (display only — backend value unchanged)

```
Decimal values (0.0–1.0) → display tiers:
  0.0–0.25   → Beginner / Low
  0.25–0.50  → Intermediate / Medium
  0.50–0.75  → Advanced / High
  0.75–1.0   → Expert / Critical

Confidence: 0.45 → "45% confidence"
Importance: 0.9  → "Critical" or "90%"
```

---

## 11. Page-by-Page Change Priorities

### COMPANY

| Page | Top 3 changes |
|---|---|
| Jobs list | Page header with Create Job CTA; humanized status badges; job cards with compensation |
| Job detail | Tab navigation (JD / Requirements / Assessment / Candidates); humanize all enums; requirements show % not decimals |
| Requirements editor | Confidence as "X% confidence"; Importance as Low/Medium/High/Critical; min_level as human level label |
| Private QB | Clearer section hierarchy; import as polished multi-step flow; coverage as visual progress bar |
| Candidate | Tabs (Overview / Assessment / Interview / Proctoring); decision at bottom after review; humanize enums |

### STUDENT

| Page | Top 3 changes |
|---|---|
| Dashboard | Welcome name + active application summary; metric cards with visual weight; skill section with empty CTA |
| Jobs feed | Compensation + deadline on cards; search input; applied indicator |
| Application detail | Visual progress timeline; humanize enums; assessment/interview in focused layout |
| Assessment | Sidebar-hidden layout during testing; larger navigator buttons; styled radio buttons |
| Interview | Current question prominent; previous turns collapsed after answered; progress indicator |
| Profile | Tab layout per section; labels on all inputs; delete capability |

### PLACEMENT OFFICER

| Page | Top 3 changes |
|---|---|
| Overview | Metric cards with visual hierarchy; funnel as visual bar; move roster to Students page |
| Students | Invite form in slide-in drawer; tab content properly separated; humanize ACTIVE status |
| Opportunities | Summary list view with details on expand; count badges on tabs; reject as modal |

---

## 12. Accessibility Issues

| Issue | Priority |
|---|---|
| All inputs use placeholder-only — no label elements anywhere | P1 |
| Error messages not linked to inputs via aria-describedby | P1 |
| Badge component: no role or aria-label | P2 |
| Focus rings: browser default only — no visible custom styling | P2 |
| Color-only differentiation in heatmap (background opacity only) | P2 |
| Assessment timer: aria-label="time remaining" — GOOD | ✓ |
| Navigator buttons have title attribute — GOOD | ✓ |
| Interview status: role="status" — GOOD | ✓ |
| Semantic h1/h2 headings used correctly per page | ✓ |

---

## 13. Responsive Issues

| Issue | Priority |
|---|---|
| Sidebar always 224px — at 768px content is only ~544px | P1 |
| Company job detail: many wide tables overflow on tablet | P1 |
| Institution dashboard: grid-cols-4 without responsive modifier | P1 |
| Sidebar has no mobile handling — no hamburger, no collapse | P1 |
| PostingFormFields: grid-cols-4 / grid-cols-5 may overflow at 768px | P1 |

---

## 14. Backend Issues Discovered (Document Only — Do NOT Fix in Frontend Pass)

See `docs/FRONTEND_BACKEND_ISSUES.md` for full details.

Summary:
1. Student self-signup → `/student` dashboard shows blank metrics for independent students (no institution) — API returns null institution. No onboarding flow.
2. `CompanyQuestionsPage` at `/company/questions` renders near-nothing (547 bytes) — primary nav item has broken UX as a top-level destination.
3. `JobDetailPage` for students (2.6KB) not deeply audited — likely very minimal.

---

## 15. Implementation Order

Per Phase 20 of the specification:
```
1. Shared design tokens (index.css CSS custom properties + font import)
2. Shared components (AppShell, PageHeader, StatusBadge humanization, Button, Input, Card, Table, EmptyState, Skeleton)
3. Company portal (Jobs → Job detail → Requirements → Assessment → Private QB → Candidate)
4. Student portal (Dashboard → Jobs → Application Detail → Profile → Assessment → Interview)
5. Placement Officer portal (Overview → Students → Opportunities)
6. Responsive fixes
7. Accessibility pass
8. Final browser polish
```

---

*Audit completed by reading all frontend source files and visually confirming app at http://localhost:5173. No code changes were made during this audit.*
