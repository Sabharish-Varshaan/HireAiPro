# Question Governance

Lifecycle: `DRAFT → VALIDATED → APPROVED → ACTIVE → RETIRED`, with `REJECTED` from DRAFT /
VALIDATED / APPROVED (and REJECTED → DRAFT for revision). `app/services/questions/governance.py`.

| Origin | Starts as | Visibility |
|---|---|---|
| Company upload (manual, paste, CSV, JSON) | VALIDATED if all checks pass, else DRAFT | COMPANY_PRIVATE |
| AI-generated for a job | VALIDATED or DRAFT | COMPANY_PRIVATE (the job's company) |
| Platform admin upload | VALIDATED / DRAFT | PLATFORM_PUBLIC, still needs APPROVED to be used |

- Only a PLATFORM_ADMIN can **promote** to the global bank; company-uploaded questions can never
  be promoted; AI questions grounded on non-public knowledge can't be promoted.
- Assessments use: own-company VALIDATED/APPROVED/ACTIVE; platform APPROVED/ACTIVE only.
- Every transition is audited.

## Validator (deterministic; `validator.py`)
schema/text length, difficulty ∈ {easy, medium, hard}, answerability (not truncated), MCQ ≥3
distinct options + valid key + no "all/none of the above", technical: ≥2 expected concepts + rubric,
coding: ≥2 `{input, expected_output}` test cases, skill alignment (BGE-M3 cosine ≥ 0.35),
grounding (reranker ≥ 0.3 against cited chunks), duplicates (cosine ≥ 0.92 within tenant scope,
via Qdrant). Failures stay DRAFT with `validation_report`.

## Import formats
CSV header: `question_text,question_type,skill,difficulty,options,correct_option,expected_concepts,test_cases`
(`|`-separated lists; `test_cases` JSON). JSON: list of objects with the same keys. Paste: one
question per blank-line-separated block. Pipeline: parse → skill normalization → difficulty
estimate if missing → rubric completion (LLM, `rubric_completion` task) if missing → validate →
private bank.
