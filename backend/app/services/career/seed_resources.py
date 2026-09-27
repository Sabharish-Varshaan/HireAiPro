"""Seed curated learning resources from seeds/learning_resources.json.

Every URL is fetched before it is stored; anything that doesn't resolve to a
2xx/3xx response is reported and skipped rather than persisted. Upserts on
(url, skill_id), so re-running is safe.

    python -m app.services.career.seed_resources            # verify + upsert
    python -m app.services.career.seed_resources --no-verify
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.models.career import LearningResource
from app.models.skills import Skill

SEED = Path(__file__).resolve().parents[3] / "seeds" / "learning_resources.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (HireAiPro resource verifier)"}


async def _check(client: httpx.AsyncClient, url: str) -> tuple[str, int | str]:
    try:
        r = await client.get(url, headers=HEADERS)
        return url, r.status_code
    except httpx.HTTPError as exc:
        return url, type(exc).__name__


async def seed(verify: bool = True) -> dict:
    items = json.loads(SEED.read_text())
    status: dict[str, int | str] = {}
    if verify:
        urls = sorted({i["url"] for i in items})
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            sem = asyncio.Semaphore(8)

            async def guarded(u):
                async with sem:
                    return await _check(client, u)

            status = dict(await asyncio.gather(*(guarded(u) for u in urls)))

    created = updated = skipped = 0
    failures = []
    async with AsyncSessionLocal() as db:
        skills = {s.canonical_name: s for s in (await db.scalars(select(Skill))).all()}
        for item in items:
            skill = skills.get(item["skill"])
            code = status.get(item["url"], 200)
            if skill is None:
                failures.append((item["url"], f"unknown skill {item['skill']}"))
                skipped += 1
                continue
            if not (isinstance(code, int) and 200 <= code < 400):
                failures.append((item["url"], code))
                skipped += 1
                continue
            row = await db.scalar(
                select(LearningResource).where(LearningResource.url == item["url"], LearningResource.skill_id == skill.id)
            )
            if row is None:
                row = LearningResource(url=item["url"], skill_id=skill.id)
                db.add(row)
                created += 1
            else:
                updated += 1
            row.title = item["title"]
            row.provider = item.get("provider")
            row.resource_type = item.get("resource_type", "article")
            row.difficulty = item.get("difficulty", "beginner")
            row.estimated_duration = item.get("estimated_duration")
            row.prerequisites = item.get("prerequisites")
            row.is_free = item.get("is_free", True)
            row.status = "ACTIVE"
        await db.commit()
    await engine.dispose()
    return {"created": created, "updated": updated, "skipped": skipped, "failures": failures}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed(verify="--no-verify" not in sys.argv)), indent=1))
