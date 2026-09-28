# RAG Security (tenant isolation)

## Payload
Every Qdrant point carries `visibility` and, as applicable, `organization_id`, `institution_id`,
`owner_id`, plus `document_id`, `skill_ids`, `source_type`, `content_hash`, `embedding_model`.

## Filter (applied by Qdrant during retrieval, never post-filtered in Python)
`TenantScope.to_filter()` (`app/services/ai_gateway/vector_store.py`):
```
visibility = PLATFORM_PUBLIC
OR (visibility = COMPANY_PRIVATE     AND organization_id = caller_org)
OR (visibility = INSTITUTION_PRIVATE AND institution_id  = caller_institution)
```
`search()` requires a scope argument. The scope is derived server-side from the caller's
memberships (`app/api/tenancy.py::scope_for`); clients can't supply a visibility.

## Payload indexes
Created for fields used in filters only: `organization_id`, `institution_id`, `visibility`,
`skill_ids`, `document_id`, `source_type` (keyword).

## Context assembly
Tenant filtering happens before reranking and before any prompt is built, so private chunks can't
reach another tenant's prompt — including prompts sent to remote providers (Groq/OpenAI).
Questions generated from private knowledge carry that visibility in `source_refs` and can never be
promoted to the platform bank.

## Tests (all passing)
`tests/security/test_tenant_isolation.py` — Company A private question + private document vs
Company B: absent from B's API lists, direct Qdrant queries, reranked context, the exact prompt
sent to the LLM (spied) and the live LLM answer, using a token that exists **only** in A's
document; A still retrieves both. `tests/security/test_api_permissions.py` — roles, job/candidate
isolation, student-to-student, institution isolation, admin self-registration blocked.

Note on an earlier false alarm: a live test once "failed" because the secret token also appeared
in Company B's *own question* and the model echoed it. That was a fixture artifact, not a leak;
the test now uses a token present only in A's private content.
