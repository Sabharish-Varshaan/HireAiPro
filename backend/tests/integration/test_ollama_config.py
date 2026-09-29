"""Ollama endpoint configuration: defaults agree with the documented port and a
wrong port is reported as unhealthy instead of silently passing."""

from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.core.config import Settings, get_settings
from app.models.enums import UserRole
from app.core.database import AsyncSessionLocal
from tests.factories import make_user

ROOT = Path(__file__).resolve().parents[3]


def test_default_and_example_use_the_host_ollama_port():
    assert Settings.model_fields["OLLAMA_BASE_URL"].default == "http://localhost:11434"
    assert dotenv_values(ROOT / ".env.example")["OLLAMA_BASE_URL"] == "http://localhost:11434"


@pytest.mark.asyncio
async def test_wrong_port_reports_ollama_unhealthy(client, monkeypatch):
    async with AsyncSessionLocal() as db:
        _, h = await make_user(db, UserRole.PLATFORM_ADMIN)
        await db.commit()
    monkeypatch.setattr(get_settings(), "OLLAMA_BASE_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    r = await client.get("/admin/ai/providers", headers=h)
    assert r.status_code == 200
    assert r.json()["ollama"]["healthy"] is False and r.json()["ollama"]["model_loaded_in_memory"] is False
