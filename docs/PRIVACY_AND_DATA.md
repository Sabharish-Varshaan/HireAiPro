# Privacy and Data

No regulatory compliance (GDPR, etc.) is claimed. This describes current behaviour.

## What is stored
Account, student profile, uploaded resume file + extracted resume claims, assessment answers,
coding submissions, interview questions/answers/rubric evaluations, optional interview audio,
skill evidence and estimates, applications and their history, notifications, audit events.

## Student controls (`/api/v1/me/*`)
- `GET /me/data` — export of everything above.
- `DELETE /me/resume` — deletes resume files and soft-deletes the claims derived from them.
- `DELETE /me/interview-data` — deletes interview audio and replaces transcript text with
  `[deleted by student]` (rubric scores already shown to recruiters are kept).
- `DELETE /me/evidence` — soft-deletes evidence and recalculates (clears the profile).
- `DELETE /me/account` — deactivates the login and de-identifies name/email.

## Access
Recruiters see a student only if the student applied to their company's job; institution staff
only their enrolled students; students only themselves. Enforced server-side (`app/api/tenancy.py`).

## Logging
`ai_runs` stores SHA-256 hashes of prompts/outputs, token counts and cost — never raw resume or
interview text. Audit metadata holds ids/statuses/counts only. Secrets are never logged or
returned (the admin provider-health endpoint reports configured/healthy only).

## Remote inference
With keys configured, prompts for routed tasks go to Groq and/or OpenAI (see
`docs/AI_ROUTING_AND_COST.md`): JD text, resume text, answers being graded, retrieved (tenant-
scoped) chunks. Use `LOCAL_ONLY=true` to keep all inference on-device. Embeddings, reranking and
speech-to-text are always local.

## Retention
No automatic expiry yet: data persists until a user deletes it via the controls above. Uploaded
files live under `backend/data/uploads/` (gitignored).
