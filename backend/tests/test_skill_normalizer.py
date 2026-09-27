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
