import asyncio
import re

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.enums import SkillRelationType
from app.models.skills import Skill, SkillAlias, SkillRelationship
from app.services.skills.taxonomy_data import TAXONOMY

PREREQUISITES: list[tuple[str, str]] = [
    ("Data Structures", "Algorithms"),
    ("Python", "Django"),
    ("Python", "FastAPI"),
    ("Python", "Flask"),
    ("Python", "Machine Learning"),
    ("Python", "Pandas"),
    ("Python", "NumPy"),
    ("JavaScript", "TypeScript"),
    ("JavaScript", "React"),
    ("JavaScript", "Node.js"),
    ("React", "Next.js"),
    ("Node.js", "Express.js"),
    ("Express.js", "REST APIs"),
    ("REST APIs", "GraphQL"),
    ("SQL", "PostgreSQL"),
    ("SQL", "MySQL"),
    ("PostgreSQL", "Database Indexing"),
    ("Object-Oriented Programming", "Design Patterns"),
    ("Docker", "Kubernetes"),
    ("Machine Learning", "Deep Learning"),
    ("Deep Learning", "Natural Language Processing"),
    ("Deep Learning", "Computer Vision"),
    ("Machine Learning", "Large Language Models"),
    ("Large Language Models", "Prompt Engineering"),
    ("Large Language Models", "Retrieval-Augmented Generation"),
    ("Algorithms", "Dynamic Programming"),
    ("Algorithms", "Graph Algorithms"),
    ("Networking Fundamentals", "AWS"),
    ("Linux Administration", "Docker"),
    ("Authentication & Authorization", "JWT"),
]

RELATED: list[tuple[str, str]] = [
    ("React", "Redux"),
    ("Vue.js", "Nuxt.js"),
    ("FastAPI", "REST APIs"),
    ("PostgreSQL", "SQLAlchemy"),
    ("AWS", "Azure"),
    ("AWS", "Google Cloud Platform"),
    ("PyTorch", "TensorFlow"),
    ("Unit Testing", "Test-Driven Development"),
    ("CI/CD", "GitHub Actions"),
    ("CI/CD", "Jenkins"),
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


async def seed_skills() -> dict:
    async with AsyncSessionLocal() as db:
        existing = {s.canonical_name: s for s in (await db.scalars(select(Skill))).all()}
        created_skills = 0
        created_aliases = 0

        name_to_skill: dict[str, Skill] = dict(existing)

        for category, items in TAXONOMY.items():
            for canonical_name, aliases in items:
                skill = name_to_skill.get(canonical_name)
                if skill is None:
                    skill = Skill(canonical_name=canonical_name, category=category)
                    db.add(skill)
                    await db.flush()
                    name_to_skill[canonical_name] = skill
                    created_skills += 1

                existing_alias_norms = {
                    a.alias_normalized
                    for a in (
                        await db.scalars(
                            select(SkillAlias).where(SkillAlias.skill_id == skill.id)
                        )
                    ).all()
                }
                for alias in aliases:
                    norm = _norm(alias)
                    if norm and norm not in existing_alias_norms:
                        db.add(
                            SkillAlias(skill_id=skill.id, alias=alias, alias_normalized=norm)
                        )
                        existing_alias_norms.add(norm)
                        created_aliases += 1

        await db.flush()

        created_rels = 0
        existing_rels = {
            (r.from_skill_id, r.to_skill_id, r.relation_type)
            for r in (await db.scalars(select(SkillRelationship))).all()
        }

        def add_rel(from_name: str, to_name: str, rel_type: SkillRelationType) -> None:
            nonlocal created_rels
            frm = name_to_skill.get(from_name)
            to = name_to_skill.get(to_name)
            if not frm or not to:
                return
            key = (frm.id, to.id, rel_type)
            if key in existing_rels:
                return
            db.add(SkillRelationship(from_skill_id=frm.id, to_skill_id=to.id, relation_type=rel_type))
            existing_rels.add(key)
            created_rels += 1

        for a, b in PREREQUISITES:
            add_rel(a, b, SkillRelationType.PREREQUISITE_OF)
        for a, b in RELATED:
            add_rel(a, b, SkillRelationType.RELATED_TO)

        await db.commit()

        total = len(name_to_skill)
        return {
            "total_skills": total,
            "created_skills": created_skills,
            "created_aliases": created_aliases,
            "created_relationships": created_rels,
        }


if __name__ == "__main__":
    result = asyncio.run(seed_skills())
    print(result)
