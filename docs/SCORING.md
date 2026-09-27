# Scoring

## skill_scoring_v1 (`app/services/evidence/estimator.py`)

Every graded action (MCQ answer, technical rubric evaluation, coding submission, interview turn,
project/certificate entry) writes a `skill_evidence` row with a `normalized_score` in `[0,1]` and
a `confidence` in `[0,1]`. Resume-derived claims also write `skill_evidence` (source_type
`RESUME_CLAIM`) purely for transparency in the UI — they are excluded from scoring.

Base weights by evidence source:

| Source | Weight |
|---|---|
| Coding (Judge0) | 0.40 |
| Technical assessment (rubric) | 0.15 |
| MCQ | 0.15 |
| Interview | 0.20 |
| Project | 0.10 |
| Certificate | 0.0 |
| Resume claim | 0.0 |

For a given (student, skill) pair, only evidence types with weight > 0 that actually exist are
used; their weights are renormalized to sum to 1 (`weight_sum` in the estimator). Within a type,
evidence is averaged with a recency multiplier (1.0 within 30 days, 0.85 within 180 days, 0.65
older) so a fresh technical answer counts more than one from months ago.

Confidence combines:
- the average `confidence` of contributing evidence,
- a diversity bonus (up to +0.15) for spanning more evidence types,
- a count bonus (up to +0.15) for more total evidence.

The result is written to `student_skills` (`estimated_level`, `confidence`, `evidence_count`,
`scoring_version`, `last_evidence_at`). The formula is versioned (`SCORING_VERSION` in config) so
a future `skill_scoring_v2` can be introduced without silently changing historical evidence.

## matching_v1 (`app/services/matching/engine.py`)

```
match_score = 0.60 * required_skill_fit
            + 0.20 * preferred_skill_fit
            + 0.15 * evidence_confidence
            + 0.05 * semantic_relevance
```

- `skill_fit = min(student_level / required_level, 1.0)` per skill, importance-weighted within
  its group (required or preferred).
- `evidence_confidence` = mean confidence across the student's `student_skills` rows that match
  the job's required/preferred skills.
- `semantic_relevance` = fraction of job skills the student has *any* stored evidence for at all
  (a coarse breadth signal, not a text-similarity score — no embeddings are in this particular
  path today; RAG/embeddings are used upstream in question generation and knowledge retrieval).

No LLM call is on this path. The stored `Match` row keeps `required_skill_fit`,
`preferred_skill_fit`, `evidence_confidence`, `semantic_relevance`, and per-skill
`strong_skills`/`partial_skills`/`missing_skills` breakdowns so both recruiter and student views
are fully explainable from stored numbers, not from a fresh LLM call.
