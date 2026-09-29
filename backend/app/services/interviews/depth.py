"""Deterministic planning for the technical interview (docs/HIRING_PIPELINE_ARCHITECTURE.md).

Pure functions, no I/O and no model: given the frozen blueprint and the turns so far, decide WHICH competency and WHICH depth layer
to ask next. The wording comes from the question pool prepared at publish time, so the candidate never waits for generation.

Depth layers for one competency:  1 core concept -> 2 why/how -> 3 applied scenario -> 4 edge/failure case -> 5 trade-off.
Adaptation (evidence = the rubric score of the previous answer on that competency):
  strong (>= STRONG)      -> go one layer deeper
  adequate                -> deeper until the scenario layer, then move on
  weak (< WEAK)           -> one diagnostic step back to a more fundamental layer, then move on
  low evaluator confidence-> one clarification at the same layer
"""

from dataclasses import dataclass, field

LAYERS = {1: "Core concept", 2: "How and why it works", 3: "Applied scenario", 4: "Edge case or failure", 5: "Trade-off"}
LAYER_KIND = {1: "conceptual", 2: "conceptual", 3: "scenario", 4: "debugging", 5: "tradeoff"}
LAYER_DIFFICULTY = {1: "easy", 2: "medium", 3: "medium", 4: "hard", 5: "hard"}
MAX_LAYER = 5
STRONG, WEAK, UNCERTAIN = 0.75, 0.4, 0.5
MAX_COMPETENCIES = 6
DEFAULT_MAX_ASKS = 4


@dataclass
class Comp:
    skill_id: str
    name: str
    importance: float
    required: bool
    share: float
    min_q: int
    max_q: int


@dataclass
class TurnState:
    skill_id: str
    layer: int
    score: float | None = None        # rubric overall score of the answer, None while unscored
    confidence: float | None = None   # evaluator confidence
    mode: str = "start"


@dataclass
class Pick:
    skill_id: str
    layer: int
    mode: str      # start | deeper | diagnostic | clarify | switch | coverage
    reason: str


def question_budget(duration_minutes: int | None, configured: int | None = None) -> int:
    """~5 minutes per substantive question, between 6 and 10 (a 30/45/60-minute interview gives 6/9/10)."""
    if configured:
        return max(3, min(int(configured), 12))
    return max(6, min(10, round((duration_minutes or 45) / 5)))


def build_blueprint(competencies: list[dict], budget: int, max_asks: int = DEFAULT_MAX_ASKS) -> list[dict]:
    """The frozen competency blueprint: importance-weighted share, question range and target depth per competency."""
    top = sorted(competencies, key=lambda c: (-c["importance"], c["name"]))[:MAX_COMPETENCIES]
    weights = [c["importance"] * (1.2 if c["required"] else 1.0) for c in top]
    total = sum(weights) or 1.0
    out = []
    for c, w in zip(top, weights):
        share = w / total
        expected = share * budget
        max_q = max(2, min(max_asks, round(expected) + 1))
        min_q = 2 if (c["required"] and expected >= 1.5) else 1
        out.append({"skill_id": c["skill_id"], "name": c["name"], "importance": c["importance"], "required": c["required"],
                    "share_pct": round(share * 100), "min_questions": min_q, "max_questions": max_q,
                    "target_depth": min(MAX_LAYER, 3 + (1 if share >= 0.25 else 0) + (1 if share >= 0.4 else 0)),
                    "difficulty_envelope": ["easy", "hard"] if share >= 0.2 else ["easy", "medium"]})
    return out


def comps_from_blueprint(bp: list[dict], budget: int) -> list[Comp]:
    return [Comp(skill_id=str(b["skill_id"]), name=b["name"], importance=b["importance"], required=b["required"],
                 share=b["share_pct"] / 100.0, min_q=b["min_questions"], max_q=b["max_questions"]) for b in bp]


def _switch(comps: list[Comp], counts: dict[str, int], exhausted: set[str], budget: int, mode: str, why: str) -> Pick | None:
    cands = [c for c in comps if c.skill_id not in exhausted and counts.get(c.skill_id, 0) < c.max_q]
    if not cands:
        return None
    # uncovered first, then the largest shortfall against the competency's share, then importance, then name (deterministic)
    cands.sort(key=lambda c: (counts.get(c.skill_id, 0) > 0, -(c.share * budget - counts.get(c.skill_id, 0)), -c.importance, c.name))
    c = cands[0]
    first = counts.get(c.skill_id, 0) == 0
    return Pick(c.skill_id, 1 if first else 2, mode if first else "switch",
                f"{why}; {c.name}: {'not yet covered' if first else 'needs more depth'}")


def plan_next(comps: list[Comp], turns: list[TurnState], budget: int, exhausted: set[str] | None = None,
              max_asks: int = DEFAULT_MAX_ASKS) -> Pick | None:
    """The next (competency, layer), or None when the budget is spent or nothing is left to ask."""
    exhausted = exhausted or set()
    if len(turns) >= budget or not comps:
        return None
    counts: dict[str, int] = {}
    for t in turns:
        counts[t.skill_id] = counts.get(t.skill_id, 0) + 1
    if not turns:
        return _switch(comps, counts, exhausted, budget, "start", "opening question")
    remaining = budget - len(turns)
    uncovered = [c for c in comps if counts.get(c.skill_id, 0) == 0 and c.skill_id not in exhausted]
    last = turns[-1]
    cur = next((c for c in comps if c.skill_id == last.skill_id), None)
    if cur is None or cur.skill_id in exhausted:
        return _switch(comps, counts, exhausted, budget, "switch", "moving on")
    n = counts.get(cur.skill_id, 0)
    if len(uncovered) >= remaining:  # no slack left: every remaining question must open an uncovered competency
        return _switch(comps, counts, exhausted, budget, "coverage", "coverage of remaining competencies")
    if n >= min(cur.max_q, max_asks):
        return _switch(comps, counts, exhausted, budget, "switch", f"{cur.name} reached its question limit")
    # low confidence: clarify once at the same layer before drawing conclusions
    if last.confidence is not None and last.confidence < UNCERTAIN and last.mode != "clarify":
        return Pick(cur.skill_id, last.layer, "clarify", f"answer evidence on {cur.name} was uncertain; clarifying at layer {last.layer}")
    sc = last.score
    if sc is None:  # not scored yet: continue one layer deeper rather than stall
        nxt = min(last.layer + 1, MAX_LAYER)
        return Pick(cur.skill_id, nxt, "deeper", f"going deeper on {cur.name} (previous answer still being scored)") if last.layer < MAX_LAYER \
            else _switch(comps, counts, exhausted, budget, "switch", f"{cur.name} depth exhausted")
    if sc >= STRONG:
        if last.layer >= MAX_LAYER:
            return _switch(comps, counts, exhausted, budget, "switch", f"strong evidence on {cur.name} through the deepest layer")
        return Pick(cur.skill_id, last.layer + 1, "deeper", f"strong answer on {cur.name}: layer {last.layer + 1}")
    if sc >= WEAK:
        if last.layer < 3:
            return Pick(cur.skill_id, last.layer + 1, "deeper", f"adequate answer on {cur.name}: layer {last.layer + 1}")
        return _switch(comps, counts, exhausted, budget, "switch", f"adequate depth reached on {cur.name}")
    if last.layer > 1 and last.mode != "diagnostic":
        return Pick(cur.skill_id, last.layer - 1, "diagnostic", f"weak answer on {cur.name}: checking fundamentals (layer {last.layer - 1})")
    return _switch(comps, counts, exhausted, budget, "switch", f"weak evidence on {cur.name} after a diagnostic step")


def turn_score(rubric: dict | None) -> tuple[float | None, float | None]:
    if not rubric or "concept_accuracy" not in rubric:
        return None, None
    s = 0.4 * rubric["concept_accuracy"] + 0.25 * rubric["reasoning"] + 0.25 * rubric["completeness"] + 0.10 * rubric["communication"]
    return s, rubric.get("evaluator_confidence")


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def choose_from_pool(rows: list, skill_id: str, layer: int, seen_texts: set[str], seen_kinds: list[str]):
    """Unseen pool question of this competency nearest to the wanted layer, preferring a question kind not just used.
    rows: objects with skill_id, layer, kind, question_text."""
    mine = [r for r in rows if str(r.skill_id) == skill_id and norm(r.question_text) not in seen_texts]
    if not mine:
        return None
    last_kind = seen_kinds[-1] if seen_kinds else None
    mine.sort(key=lambda r: (abs((r.layer or 2) - layer), (r.kind == last_kind), (r.layer or 2), r.question_text))
    return mine[0]
