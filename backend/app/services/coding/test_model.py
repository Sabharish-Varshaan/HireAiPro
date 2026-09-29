"""Coding test-case structure: visible samples vs hidden tests.

A test is {"input", "expected_output", "visible": bool, "category": str}. Visible samples are shown to the
candidate and used by Run; hidden tests are used only by Submit and never leave the server. Older questions have
no flags, for which the first samples are treated as visible.
"""

MIN_TOTAL = 8       # generated questions must keep at least this many verified tests
MIN_VISIBLE = 2
MAX_VISIBLE = 3
MIN_CATEGORIES = 4
CATEGORIES = ("normal", "boundary_minimum", "empty", "single_element", "maximum_size", "duplicates", "ordering",
              "negative_values", "all_equal", "special_case", "performance")


def visible_indexes(tests: list[dict]) -> list[int]:
    flagged = [i for i, t in enumerate(tests) if t.get("visible") is True]
    if flagged or any("visible" in t for t in tests):
        return flagged[:MAX_VISIBLE]
    return list(range(min(2 if len(tests) >= 3 else 1, len(tests))))  # legacy questions without flags


def sample_view(tests: list[dict]) -> list[dict]:
    return [{"input": str(tests[i].get("input", "")), "expected_output": str(tests[i].get("expected_output", ""))}
            for i in visible_indexes(tests or [])]


def hidden_count(tests: list[dict]) -> int:
    return len(tests) - len(visible_indexes(tests))


def normalize(kept: list[dict]) -> list[dict]:
    """After pruning: dedupe by input, cap visible at MAX_VISIBLE, guarantee MIN_VISIBLE samples."""
    seen, out = set(), []
    for t in kept:
        key = str(t.get("input", "")).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append({"input": str(t["input"]), "expected_output": str(t["expected_output"]),
                    "visible": bool(t.get("visible")), "category": str(t.get("category") or "normal")})
    vis = [i for i, t in enumerate(out) if t["visible"]]
    for i in vis[MAX_VISIBLE:]:
        out[i]["visible"] = False
    need = MIN_VISIBLE - min(len(vis), MAX_VISIBLE)
    if need > 0:  # promote the simplest hidden tests (earliest, preferring 'normal') to samples
        pool = sorted((i for i, t in enumerate(out) if not t["visible"]), key=lambda i: (out[i]["category"] != "normal", i))
        for i in pool[:need]:
            out[i]["visible"] = True
    return out


def depth_problems(tests: list[dict]) -> list[str]:
    problems = []
    if len(tests) < MIN_TOTAL:
        problems.append(f"only {len(tests)} verified tests (need {MIN_TOTAL}+)")
    if sum(1 for t in tests if t.get("visible")) < MIN_VISIBLE:
        problems.append("fewer than 2 visible samples")
    cats = {t.get("category") for t in tests if t.get("category")}
    if len(cats) < MIN_CATEGORIES:
        problems.append(f"tests cover only {len(cats)} distinct categories (need {MIN_CATEGORIES}+)")
    return problems
