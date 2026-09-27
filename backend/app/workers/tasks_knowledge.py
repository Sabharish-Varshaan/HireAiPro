import uuid

from app.core.database import AsyncSessionLocal
from app.models.knowledge import KnowledgeSource
from app.models.skills import Skill
from app.services.audit import audit
from app.services.knowledge.service import ingest_source
from app.workers.celery_app import celery_app
from app.workers.jobs import TRANSIENT, PermanentJobError, run_tracked
from app.workers.utils import run_async


async def ingest(source_id: uuid.UUID, use_agent: bool = True, actor_user_id: uuid.UUID | None = None) -> dict:
    """Ingests one registered source. With use_agent the Knowledge Agent
    orchestrates; the underlying pipeline is idempotent either way (chunk ids
    are derived from document+index and unchanged content is skipped)."""
    async with AsyncSessionLocal() as db:
        src = await db.get(KnowledgeSource, source_id)
        if src is None:
            raise PermanentJobError("knowledge source not found")
        if use_agent:
            from app.agents.knowledge_agent import SourceSpec, run_knowledge_agent

            skill = await db.get(Skill, uuid.UUID(src.skill_ids[0]))
            pkg = await run_knowledge_agent(
                db, skill_name=skill.canonical_name,
                sources=[SourceSpec(title=src.title, source_type=src.source_type, source_uri=src.source_uri, raw_text=src.raw_text)],
                visibility=src.visibility, organization_id=src.organization_id, institution_id=src.institution_id,
                owner_user_id=src.owner_user_id,
            )
            result = pkg.model_dump(mode="json")
        else:
            result = await ingest_source(db, src)
        await db.refresh(src)
        await audit(db, actor_user_id, "knowledge_source_ingested", "knowledge_source", src.id,
                    organization_id=src.organization_id, metadata={"status": src.status, "chunks": src.chunk_count})
        await db.commit()
        return result


@celery_app.task(name="knowledge.ingest", bind=True, autoretry_for=TRANSIENT, retry_backoff=10, max_retries=3)
def ingest_task(self, source_id: str, actor_user_id: str | None = None) -> dict:
    return run_async(lambda: run_tracked(
        f"knowledge:{source_id}", "knowledge_ingestion", {"source_id": source_id}, self.request.id,
        lambda: ingest(uuid.UUID(source_id), actor_user_id=uuid.UUID(actor_user_id) if actor_user_id else None),
    ))
