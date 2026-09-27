import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.skills import Skill
from app.schemas.skills import SkillOut

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/by-ids", response_model=list[SkillOut])
async def get_skills_by_ids(ids: str, db: AsyncSession = Depends(get_db)):
    """ids: comma-separated UUIDs. Used by the frontend to resolve skill
    names for a batch of ids in one call."""
    id_list = [uuid.UUID(i) for i in ids.split(",") if i]
    if not id_list:
        return []
    return (await db.scalars(select(Skill).where(Skill.id.in_(id_list)))).all()


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found")
    return skill


@router.get("", response_model=list[SkillOut])
async def list_skills(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Skill)
    if q:
        stmt = stmt.where(Skill.canonical_name.ilike(f"%{q}%"))
    if category:
        stmt = stmt.where(Skill.category == category)
    stmt = stmt.limit(limit)
    return (await db.scalars(stmt)).all()


@router.get("/categories", response_model=list[str])
async def list_categories(db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Skill.category).distinct())).all()
    return sorted(rows)
