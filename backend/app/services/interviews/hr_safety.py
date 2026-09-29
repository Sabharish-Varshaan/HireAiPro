"""Fairness guard for the HR interview. Applied to every HR question before it can enter a pool (company bank, curated, generated) and to
every stored observation. Deliberately conservative: a question that mentions a protected or sensitive topic is dropped, never rephrased.

The HR stage records job-relevant observations only. It never infers personality, emotion, honesty, mental state, culture fit from
accent, and it never scores a person."""

import re

_TERMS = [
    r"relig\w*", r"church", r"mosque", r"temple", r"\bgod\b", r"\bcaste\b", r"\brace\b", r"racial\w*", r"ethnic\w*", r"nationalit\w*",
    r"pregnan\w*", r"maternity", r"marital", r"\bmarried\b", r"\bsingle\b", r"spouse", r"husband", r"\bwife\b", r"\bchildren\b", r"\bkids\b",
    r"family plan\w*", r"have (a )?famil\w*", r"sexual", r"orientation", r"\bgay\b", r"lesbian", r"transgender", r"\bgender\b",
    r"politic\w*", r"\bparty\b", r"\bvote\w*", r"medical", r"illness", r"disease", r"disabilit\w*", r"\bhealth\w*", r"mental", r"depress\w*",
    r"anxiety", r"therapy", r"medication", r"\bage\b", r"how old", r"date of birth", r"birthday", r"accent", r"appearance", r"\bweight\b",
    r"\bheight\b", r"citizenship", r"criminal", r"arrest\w*", r"union member", r"personality (disorder|type)", r"lie\b", r"honest\w*",
    r"emotion\w*", r"trustworth\w*",
]
_RE = re.compile("|".join(_TERMS), re.I)

BLOCKED_TOPICS_DESCRIPTION = ("religion, race or ethnicity, nationality, pregnancy or family plans, marital status, sexual orientation or gender identity, "
                              "political beliefs, medical conditions or disability, age, appearance, accent, criminal history, union membership")


def sensitive_hits(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _RE.finditer(text or "")})


def is_safe_question(text: str) -> bool:
    t = (text or "").strip()
    return 15 <= len(t) <= 400 and not sensitive_hits(t)


def clean_observation(items: list[str]) -> list[str]:
    """Drops any observation that mentions a sensitive topic (for example one the candidate volunteered)."""
    return [i.strip() for i in items if i and i.strip() and not sensitive_hits(i)][:6]
