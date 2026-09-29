# Proctoring

Objective, browser-level monitoring for assessments and AI interviews. It records **facts** (a
timestamped event log) for a human reviewer. It never produces a cheating score, risk level, or
automated decision.

## What is and is not monitored
| Monitored (events only) | Not done, ever |
|---|---|
| camera track available / ended / muted | video or audio recording |
| microphone track available / ended / muted, sustained absence of signal | screen recording |
| fullscreen entered / exited | face recognition, gaze or emotion analysis |
| tab hidden / visible (with hidden duration) | keystroke biometrics |
| window blur / focus | automated cheating score or accusation |
| browser offline / online (with duration) | new TTS/LLM models |
| session heartbeat (gaps detected **server-side**) | |

The same lists come from `GET /api/v1/proctoring/policy`, and the consent screen shows them verbatim.

## Flow (student)
1. **Consent.** The consent text is shown and `consent_at` is persisted. No device prompt appears before consent.
2. **System check.** This makes a single `getUserMedia({video, audio})` call with a visible preview. It samples a Web Audio
   analyser level for ~4 s, checks `navigator.onLine` plus an authenticated backend round trip (latency shown),
   and checks `document.fullscreenEnabled` and the browser APIs. The report is posted to `/preflight`; the server
   recomputes pass/fail from the required checks (`PROCTOR_*_REQUIRED`).
3. **Start.** The student enters fullscreen with a 5 s timeout; some embedded browsers never settle the
   request, and the student then gets a clear message. `/start` requires consent and a PASSED preflight.
4. **Monitoring.** Listeners cover `fullscreenchange`, `visibilitychange`, `blur`/`focus` and `offline`/`online`, plus
   track `onended`/`onmute`/`onunmute`. `MIC_NO_SIGNAL` fires once after 60 s below the RMS threshold, because silence
   alone is normal. A heartbeat is sent every `PROCTOR_HEARTBEAT_SECONDS` (7). Events are debounced
   client-side (1.5 s per type), batched every 5 s (≤50 per batch, retried when offline), and deduplicated again
   server-side (`PROCTOR_DEDUPE_WINDOW_MS`).
5. **Overlays.** "Please return to fullscreen. This event has been recorded." / camera or mic stopped /
   offline. The session is never auto-terminated.
6. **Complete.** On submit or finish, events are flushed, `/complete` is called, **all tracks are stopped**
   (the camera light turns off), the AudioContext is closed and fullscreen is exited. Tracks are also released on unmount.

The interview voice recorder reuses the session's microphone track instead of opening a second one.

## Server gating
`PROCTOR_ENFORCE=true` (default): starting an assessment attempt or an interview without an ACTIVE,
consented, PASSED session returns **HTTP 428** `{"code": "PROCTORING_REQUIRED"}`. Tests default to
`false` and enable it explicitly.

Clients cannot forge `HEARTBEAT_*`, `SYSTEM_CHECK_*` or `SESSION_*` events (422). Heartbeat loss is
detected by the server: when the gap exceeds `PROCTOR_HEARTBEAT_LOST_AFTER_SECONDS` (25), the next
heartbeat records `HEARTBEAT_LOST` (at the last heartbeat) and `HEARTBEAT_RESTORED` (with duration), both `source=server`.
A development-only hook, `window.__proctorTest.pauseHeartbeat(ms)`, exists for QA and is not present in production builds.

## Storage
- `proctoring_sessions`: kind, links to the attempt or interview, consent_at, required devices, preflight
  status and report, status, last heartbeat.
- `proctoring_events`: type, occurred_at, duration_ms, severity (info/notice), source (client/server),
  metadata.

Creating a session locks the application row, so concurrent creates resume one session.

## Review
`GET /api/v1/proctoring/review/by-application/{id}` is available to the owning company, the enrolled
student's institution and admins. Students get 403, and other companies and institutions are denied. It returns
per-session counts (fullscreen exits, tab switches, window blurs, camera/mic interruptions, network outages,
heartbeat interruptions), time tab-hidden, time disconnected, duration, and the full timeline. Shown on the
company candidate page and the institution student page ("View Timeline").

## Settings
`PROCTOR_ENFORCE`, `PROCTOR_FULLSCREEN_REQUIRED`, `PROCTOR_CAMERA_REQUIRED`, `PROCTOR_MICROPHONE_REQUIRED`,
`PROCTOR_HEARTBEAT_SECONDS=7`, `PROCTOR_HEARTBEAT_LOST_AFTER_SECONDS=25`, `PROCTOR_DEDUPE_WINDOW_MS=1500`.

## Verification status
- Backend: `tests/integration/test_proctoring.py` (8 tests). Covers consent and device gating, the 428 gate, dedupe and forged
  types, the server heartbeat gap, reviewer access and counts, and that other students cannot touch a session. The concurrent-create test is a
  smoke test only: the in-process client did not reproduce the race without the lock.
- Browser E2E (2026-09-29) ran with **AUTOMATED DEVICE SIMULATION**. The canvas and oscillator media and the fullscreen
  shim were injected, because the in-app browser denies real camera/mic and cannot grant fullscreen. The real-device
  path in that browser correctly failed the check (camera/microphone FAILED, no start button).
  **A real-device pass has not been tested**; run it in a normal Chrome/Safari window.
