import pytest

from app.services.skills.normalizer import normalize_skill_name


@pytest.mark.asyncio
async def test_exact_canonical_match(db):
    skill_id, confidence = await normalize_skill_name(db, "Python")
    assert skill_id is not None
    assert confidence == 1.0


@pytest.mark.asyncio
async def test_alias_match(db):
    skill_id, confidence = await normalize_skill_name(db, "postgres")
    assert skill_id is not None
    assert confidence == 1.0


@pytest.mark.asyncio
async def test_fuzzy_match_close_typo(db):
    skill_id, confidence = await normalize_skill_name(db, "Pythoon")
    assert skill_id is not None
    assert 0.86 <= confidence < 1.0


@pytest.mark.asyncio
async def test_unrelated_text_does_not_match(db):
    skill_id, confidence = await normalize_skill_name(db, "Quantum Basket Weaving Nonsense")
    assert skill_id is None


@pytest.mark.asyncio
async def test_empty_string_returns_none(db):
    skill_id, confidence = await normalize_skill_name(db, "")
    assert skill_id is None
    assert confidence == 0.0


@pytest.mark.asyncio
async def test_taxonomy_has_at_least_300_active_skills(db):
    from sqlalchemy import func, select

    from app.models.skills import Skill

    n = await db.scalar(select(func.count()).select_from(Skill).where(Skill.is_active.is_(True)))
    assert n >= 300


@pytest.mark.asyncio
@pytest.mark.parametrize("alias,canonical", [
    ("k8s", "Kubernetes"), ("sklearn", "Scikit-learn"), ("Postgres", "PostgreSQL"), ("JS", "JavaScript"),
    ("TS", "TypeScript"), ("golang", "Go"), ("airflow", "Apache Airflow"), ("mssql", "Microsoft SQL Server"),
    ("hugging face", "Hugging Face Transformers"), ("wasm", "WebAssembly"), ("gke", "Google Kubernetes Engine"),
    ("Spring Data JPA", "Spring Data JPA"), ("OAuth 2.0", "OAuth 2.0"),
])
async def test_aliases_resolve_to_canonical(db, alias, canonical):
    from app.models.skills import Skill

    skill_id, conf = await normalize_skill_name(db, alias)
    assert skill_id is not None, alias
    assert (await db.get(Skill, skill_id)).canonical_name == canonical


@pytest.mark.asyncio
async def test_generic_words_do_not_become_skills(db):
    for word in ("experience", "team player", "fast learner", "backend"):
        skill_id, _ = await normalize_skill_name(db, word)
        assert skill_id is None, word


@pytest.mark.asyncio
async def test_no_alias_shadows_another_canonical_name(db):
    import re

    from sqlalchemy import select

    from app.models.skills import Skill, SkillAlias

    canon = {re.sub(r"[^a-z0-9]+", "", s.canonical_name.lower()): s.id for s in (await db.scalars(select(Skill))).all()}
    for a in (await db.scalars(select(SkillAlias))).all():
        assert canon.get(a.alias_normalized, a.skill_id) == a.skill_id, a.alias
