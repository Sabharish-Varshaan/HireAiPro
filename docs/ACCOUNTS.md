# Accounts and Invitations

Active roles: **Placement Officer**, **Company (Recruiter)**, **Student**. Platform Admin is created only with
`python -m app.cli create-admin` (password prompt or env, ≥12 chars). Institution Admin, Faculty and Department Head are deferred: no signup, no UI.

| Role | How the account is created |
|---|---|
| Placement Officer | `POST /auth/signup` with `institution_name` → user + institution + `InstitutionMember(PLACEMENT_OFFICER)` |
| Recruiter | `POST /auth/signup` with `company_name` → user + organization + `OrganizationMember(COMPANY_ADMIN)` (one primary recruiter per company; no team management) |
| Student (institutional) | Placement Officer invites/imports → `invitations` row → link → student **chooses their own password** at `/claim` |
| Student (independent) | Self-signup is retained deliberately so students can apply to open-market jobs |

Passwords: argon2 hash only. No default, temporary or officer-known password exists anywhere.

**Invitations** (`invitations`): 256-bit random token, only `sha256(token)` stored, single use (atomic claim), expires after
`INVITE_TTL_HOURS` (72), role- and institution-bound; resending revokes older open links. Unknown, used, revoked and expired
tokens all return the same message. **Password reset** (`password_resets`): same properties, `RESET_TTL_MINUTES` (60);
`/auth/password/forgot` returns the same 202 for known and unknown emails and sends nothing to disabled accounts.

**Email:** no provider is integrated. In `development`/`demo` messages are written to `email_outbox` and shown at
`/dev/outbox` (`GET /api/v1/dev/email-outbox`). With `APP_ENV=production` nothing is written and the endpoint answers 404.
Signup of self-registered users does **not** verify email ownership (limitation); invited users prove mailbox access by holding the token.

Disabled users (`users.is_active=false`): login fails and existing tokens stop working on the next request.
Tests: `tests/integration/test_accounts.py`.
