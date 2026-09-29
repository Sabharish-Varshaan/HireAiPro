"""The three sandboxed coding languages.

Business identifiers are the stable keys (python / javascript / cpp); display
strings are UI only. Judge0 language ids are NOT hardcoded: they are resolved
from the running Judge0's GET /languages by name and cached, so they always
match the image actually deployed (infra/judge0/languages_active.rb).
"""

import time

import httpx

from app.core.config import get_settings

settings = get_settings()

SUPPORTED_LANGUAGES: dict[str, dict] = {
    "python": {"display_name": "Python 3", "monaco": "python", "judge0_name_prefix": "Python (3."},
    "javascript": {"display_name": "JavaScript (Node.js)", "monaco": "javascript", "judge0_name_prefix": "JavaScript (Node.js"},
    "cpp": {"display_name": "C++17", "monaco": "cpp", "judge0_name_prefix": "C++17 ("},
}

_CACHE_TTL_S = 300
_cache: dict = {"at": 0.0, "ids": {}, "names": {}}


class LanguageUnavailable(Exception):
    """Judge0 is reachable but does not offer this language."""


def allowed_for_question(question) -> list[str]:
    allowed = getattr(question, "allowed_languages", None) or list(SUPPORTED_LANGUAGES)
    return [lang for lang in allowed if lang in SUPPORTED_LANGUAGES]


async def resolve_judge0_ids(force: bool = False) -> dict[str, dict]:
    """{lang: {"judge0_language_id": int, "judge0_name": str}} from the live Judge0.
    Raises httpx errors when Judge0 is unreachable (callers treat that as unavailable)."""
    if not force and _cache["ids"] and time.monotonic() - _cache["at"] < _CACHE_TTL_S:
        return {k: {"judge0_language_id": v, "judge0_name": _cache["names"][k]} for k, v in _cache["ids"].items()}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{settings.JUDGE0_URL}/languages")
        resp.raise_for_status()
        live = resp.json()
    ids, names = {}, {}
    for key, spec in SUPPORTED_LANGUAGES.items():
        match = [lang for lang in live if lang["name"].startswith(spec["judge0_name_prefix"])]
        if len(match) == 1:
            ids[key], names[key] = match[0]["id"], match[0]["name"]
    _cache.update(at=time.monotonic(), ids=ids, names=names)
    return {k: {"judge0_language_id": v, "judge0_name": names[k]} for k, v in ids.items()}


async def judge0_id_for(language: str) -> int:
    ids = await resolve_judge0_ids()
    if language not in ids:
        ids = await resolve_judge0_ids(force=True)
    if language not in ids:
        raise LanguageUnavailable(f"Judge0 does not offer {language!r}")
    return ids[language]["judge0_language_id"]
