# Agents

Four agents, each a thin orchestration layer over deterministic services. The rule throughout:
**services compute, agents decide when/what to ask the AI Gateway for and record the run.**

## Knowledge Agent (`app/agents/knowledge_agent.py`)
Ingests an admin-approved source (local document or curated URL) for a skill, chunks it, embeds
it with BGE-M3, and stores it in the `knowledge_chunks` Qdrant collection with skill/source/tenant
payload. Provenance (`source_id`, chunk id) is always kept so generated questions can cite where
they came from.

## Assessment Agent (`app/agents/assessment_agent.py`)
Given a job's *confirmed* skills, builds a deterministic blueprint
(`app/services/assessments/blueprint.py`), retrieves existing company/platform questions per
skill+type, and only calls the AI Gateway to generate the ones that are missing
(`app/services/assessments/generator.py::generate_missing_question`). Every generated question is
structurally validated before being persisted; validation failures stay in `DRAFT` for an admin to
review rather than silently entering the assessment. Every run is logged to `agent_runs`.

## Interview Agent (`app/agents/interview_agent.py`)
Competency selection is deterministic (`app/services/interviews/selector.py`): it picks the
job-required skill with the highest importance-weighted uncertainty, skipping skills already
answered `MAX_ASKS_PER_SKILL` times or already above the confidence threshold. The agent's own job
is narrower than "decide what to ask" — it phrases a concrete question for the skill the selector
already chose, and afterwards scores the student's answer against a rubric via
`evaluate_turn_answer`. It never writes to `student_skills` directly; it writes `skill_evidence`,
which the estimator later folds in.

## Career Agent (`app/agents/career_agent.py`)
Gaps are calculated deterministically first (`app/services/career/gaps.py::calculate_skill_gaps`),
ordered by `gap * importance`, then expanded with prerequisite skills from `skill_relationships`.
The AI Gateway is only asked to write a short encouraging summary and a one-line rationale per
step — it cannot change which skills appear or their order, and it cannot invent a resource:
`resource_id`/`resource_title` are looked up from `learning_resources`, or left `null` if none
exists yet. If the AI Gateway call fails, the roadmap still builds with a generic summary — the
core flow degrades gracefully rather than failing outright.

## Shared plumbing
- `app/agents/model_factory.py` is the only place that talks to PydanticAI's model layer; it
  points at Ollama through PydanticAI's OpenAI-compatible provider.
- All raw LLM calls, structured or not, go through `app/services/ai_gateway/gateway.py`, which is
  the only module allowed to know it's Ollama today (see `docs/PRODUCTION_SCALING.md`).
