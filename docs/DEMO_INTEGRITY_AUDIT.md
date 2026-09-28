# Demo Integrity Audit

Date: 2026-09-28/29. Scope: every tracked or new file under `backend/app` and `frontend/src`.

## 1. Pattern search

| Pattern | Hits | Verdict |
|---|---|---|
| mock / fake / dummy / hardcoded / demoData / sampleResult / fakeScore / mockMatch / mockCandidate | 2 | Both are **taxonomy skill names** ("Mocking", "Mockito"/"Mocha") in `taxonomy_data.py`. No mock data. |
| TODO / FIXME / bypass / skipValidation / demo_mode | 0 | — |
| `random.` / `randint` / `Math.random` | 0 | No random scores anywhere. |
| `asyncio.sleep` / `time.sleep` (fake delays) | 0 | — |
| `setTimeout(` | 2 → 1 | `AssessmentRunner` 800 ms autosave debounce (legitimate). The fixed 3 s "refresh after recompute" in `CompanyJobDetailPage` was **replaced** by polling the real `matching` processing job. |
| bare `except:` | 0 | — |
| `except …: pass` | 3 → 1 | `gateway._record_run` swallowed ai_run-logging failures silently: **fixed**, now `logger.exception` (a lost cost row would under-count the budget governor). `me._delete_file` OSError: **fixed**, now logs a warning. `admin.ai_providers` Ollama `/api/ps` probe: kept; failure means "not loaded" in a health readout. |
| broad `except Exception` | 14 | All reviewed: each records the error (ai_runs FAILED, knowledge source FAILED + message, resume FAILED status, agent run fallback reason, 422/503 to the user) or re-raises. None returns success. |

## 2. Implementation-integrity checks (verified live, see QA report)

- Scores: MCQ deterministic; technical answers scored by rubric LLM calls, each an `ai_runs` row; total = mean of per-question scores (69.0% = 8.28/12 verified).
- Skill levels: only `SkillEstimator` writes `student_skills`; 9 RESUME_CLAIM rows produced 0 student_skills.
- Matching: `matching_v1` deterministic; UI percentages equal the `matches` row (81.4 / 88.4 / 69.2).
- Coding: real execution, labelled `local_fallback` (development only) because Judge0 cannot run on macOS cgroup v2.
- Analytics: SQL aggregates; changing an application to OFFER changed the dashboard (anti-cheat test).
- Provider fallback: simulated with process-only env overrides; `.env` md5 unchanged.
- No seed writes results: seeds cover taxonomy, aliases, relationships, question bank, learning resources only.

## 3. Bugs found and fixed during this audit/QA

See the final QA report; each fix has a regression test where behaviour changed
(interview no-repeat, notifications dedupe, analytics gap sign + cohort filter, deactivated users, inactive skill search).
