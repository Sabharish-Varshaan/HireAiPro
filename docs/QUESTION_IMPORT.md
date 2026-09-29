# Company-private question import

Route: Company -> Jobs -> Job -> Private question bank (`/company/jobs/:jobId/question-bank`).

## Ownership
Imported and manually created questions are always `visibility=COMPANY_PRIVATE` with `organization_id=<company>`.
Provenance: COMPANY_IMPORT, COMPANY_MANUAL, AI_GENERATED_COMPANY_PRIVATE. Nothing is ever written as platform or global.

## Pipeline
Upload -> parse -> validate -> skill normalize -> duplicate detect -> preview -> review (exclude / resolve skill) -> confirm.
Rows are held in `question_import_batches.rows` (JSONB) until confirm; only confirm creates questions and indexes them in Qdrant with the
organization payload.

- Formats: Excel (Instructions / Questions / Metadata sheets), CSV, JSON. Templates are generated per company, job and assessment
  (`GET /question-imports/template?job_id&format`). Limits: 500 rows, 2 MB.
- Types: MCQ and TECHNICAL_WRITTEN. Coding import is rejected.
- Row statuses: READY, WARNING, INVALID, DUPLICATE, NEEDS_SKILL_MAPPING.
- Skills: aliases go through `normalize_skill_name` (for example "Postgres" maps to PostgreSQL); unknown skills need a manual mapping.
- Duplicates: content hash within the file, the company's bank and the current assessment, plus semantic near-duplicates under
  `TenantScope(organization_id)`. Other companies' questions are never compared.
- Template metadata IDs are never trusted: a template generated for another company is rejected (422) with zero rows imported.

## Reuse and coverage
`GET /question-imports/coverage` and the Coverage table show needed / available / selected. `POST /assessments/jobs/{job_id}/questions`
attaches an existing private question to a job's draft assessment (creating the draft on demand); the same question can serve several
jobs. Attach is refused for published assessments (409) and for foreign or unvalidated questions.
Builder priority: company private, then approved platform, then AI generation.

## Isolation (tested)
`tests/integration/test_company_question_import.py` uses a random `A_ONLY_PRIVATE_TOKEN_*` and checks Company B cannot reach it by list,
keyword search, semantic search, direct ID, attach, pool prompts or AI generation; tampered templates are rejected; students never receive
answer keys.

## Known limitations
- The legacy `/questions/import*` endpoints still persist immediately (platform admin and tests).
- The template's `assessment_id` is empty until a draft assessment exists.
