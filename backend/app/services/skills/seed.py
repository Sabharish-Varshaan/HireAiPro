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

PREREQUISITES += [
    ("Python", "Pydantic"), ("Pydantic", "FastAPI"), ("REST APIs", "FastAPI"), ("HTTP", "REST APIs"),
    ("TCP/IP", "HTTP"), ("Java", "Spring Boot"), ("Spring Boot", "Spring Security"), ("Spring Boot", "Spring Data JPA"),
    ("SQL", "SQL Window Functions"), ("SQL", "Query Optimization"), ("Database Indexing", "Query Optimization"),
    ("SQL", "Transactions & Isolation Levels"), ("PostgreSQL", "pgvector"), ("Docker", "Docker Compose"),
    ("Kubernetes", "Helm"), ("Kubernetes", "AWS EKS"), ("Kubernetes", "Istio"), ("Git", "Git Branching Strategies"),
    ("Git", "CI/CD"), ("CI/CD", "GitOps"), ("Kubernetes", "Argo CD"), ("Linux Administration", "systemd"),
    ("Unix Command Line", "Linux Administration"), ("Unix Command Line", "Shell Scripting"),
    ("Hash Tables", "Data Structures"), ("Linked Lists", "Data Structures"), ("Stacks & Queues", "Data Structures"),
    ("Tree Data Structures", "Graph Algorithms"), ("Recursion", "Backtracking"), ("Recursion", "Dynamic Programming"),
    ("Sorting Algorithms", "Binary Search"), ("Time & Space Complexity", "Algorithms"), ("Algorithms", "System Design"),
    ("Distributed Systems", "System Design"), ("NumPy", "Pandas"), ("Pandas", "Exploratory Data Analysis"),
    ("Statistical Analysis", "Machine Learning"), ("Linear Algebra", "Machine Learning"), ("Probability", "Statistical Analysis"),
    ("Calculus", "Gradient Descent"), ("Gradient Descent", "Deep Learning"), ("NumPy", "PyTorch"), ("NumPy", "TensorFlow"),
    ("Deep Learning", "PyTorch"), ("Deep Learning", "Convolutional Neural Networks"), ("Deep Learning", "Attention Mechanisms"),
    ("Attention Mechanisms", "Large Language Models"), ("Large Language Models", "Fine-Tuning LLMs"),
    ("Vector Embeddings", "Semantic Search"), ("Semantic Search", "Retrieval-Augmented Generation"),
    ("Machine Learning", "Scikit-learn"), ("Machine Learning", "Model Evaluation"), ("Machine Learning", "MLOps"),
    ("SQL", "Data Modeling"), ("Python", "PySpark"), ("Apache Spark", "PySpark"), ("Data Pipelines", "Apache Airflow"),
    ("SQL", "dbt"), ("JavaScript", "Node.js"), ("TypeScript", "NestJS"), ("Node.js", "NestJS"), ("React", "React Router"),
    ("React", "Redux"), ("HTML", "CSS"), ("CSS", "Tailwind CSS"), ("HTML", "JavaScript"), ("JavaScript", "Vue.js"),
    ("TypeScript", "Angular"), ("Authentication & Authorization", "OAuth 2.0"), ("OAuth 2.0", "OpenID Connect"),
    ("Application Security", "Threat Modeling"), ("Networking Fundamentals", "TLS/SSL"), ("Cryptography Basics", "TLS/SSL"),
    ("Unit Testing", "Integration Testing"), ("Unit Testing", "Test-Driven Development"), ("Python", "PyTest"),
    ("JavaScript", "Jest"), ("Java", "JUnit"), ("AWS", "AWS S3"), ("AWS", "AWS EC2"), ("AWS", "AWS IAM"),
    ("AWS", "Serverless (Lambda)"), ("Object-Oriented Programming", "Java"),
    ("Microservices Architecture", "Service Mesh"), ("Message Queues", "Event-Driven Architecture"),
    ("Event-Driven Architecture", "Event Sourcing"), ("Design Patterns", "Clean Architecture"),
]

PARENT: list[tuple[str, str]] = [
    ("AWS", "AWS S3"), ("AWS", "AWS EC2"), ("AWS", "AWS IAM"), ("AWS", "AWS RDS"), ("AWS", "AWS ECS"),
    ("AWS", "AWS EKS"), ("AWS", "Amazon CloudFront"), ("AWS", "AWS CloudFormation"), ("AWS", "Amazon Redshift"),
    ("Azure", "Azure DevOps"), ("Azure", "Azure Functions"), ("Google Cloud Platform", "Google Kubernetes Engine"),
    ("Google Cloud Platform", "BigQuery"), ("Google Cloud Platform", "Google Cloud Run"),
    ("Data Structures", "Hash Tables"), ("Data Structures", "Linked Lists"), ("Data Structures", "Tree Data Structures"),
    ("Data Structures", "Stacks & Queues"), ("Algorithms", "Sorting Algorithms"), ("Algorithms", "Graph Algorithms"),
    ("Algorithms", "Dynamic Programming"), ("Algorithms", "Greedy Algorithms"), ("Algorithms", "Binary Search"),
    ("Machine Learning", "Deep Learning"), ("Deep Learning", "Convolutional Neural Networks"),
    ("Deep Learning", "Recurrent Neural Networks"), ("Natural Language Processing", "Named Entity Recognition"),
    ("Natural Language Processing", "Sentiment Analysis"), ("Natural Language Processing", "Text Classification"),
    ("Computer Vision", "Object Detection"), ("Computer Vision", "Image Segmentation"),
    ("Monitoring & Observability", "OpenTelemetry"), ("Monitoring & Observability", "Prometheus"),
    ("Monitoring & Observability", "Grafana"), ("Application Security", "OWASP Top 10"),
    ("SQL", "SQL Window Functions"), ("Spring Boot", "Spring Security"),
]

RELATED: list[tuple[str, str]] = [
    ("Playwright", "Cypress"), ("Playwright", "Selenium"), ("Vitest", "Jest"), ("Terraform", "Pulumi"),
    ("MySQL", "MariaDB"), ("PostgreSQL", "MySQL"), ("Redis", "Memcached"), ("Kafka", "RabbitMQ"),
    ("Apache Kafka", "RabbitMQ"), ("Qdrant", "Pinecone"), ("Qdrant", "Milvus"), ("pgvector", "Vector Databases"),
    ("Qdrant", "Vector Databases"), ("LangChain", "LlamaIndex"), ("Tableau", "Power BI"), ("Pandas", "Polars"),
    ("Apache Airflow", "Dagster"), ("Apache Airflow", "Prefect"), ("React Native", "Flutter"),
    ("Snowflake", "BigQuery"), ("Docker", "Podman"), ("Argo CD", "GitOps"), ("Datadog", "Grafana"),
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

        canonical_norms = {_norm(n) for items in TAXONOMY.values() for n, _ in items}
        global_alias_norms = {a.alias_normalized for a in (await db.scalars(select(SkillAlias))).all()}

        for category, items in TAXONOMY.items():
            for canonical_name, aliases in items:
                skill = name_to_skill.get(canonical_name)
                if skill is None:
                    skill = Skill(canonical_name=canonical_name, category=category)
                    db.add(skill)
                    await db.flush()
                    name_to_skill[canonical_name] = skill
                    created_skills += 1

                for alias in aliases:
                    norm = _norm(alias)
                    # an alias may never shadow another canonical name or an alias already taken
                    if not norm or norm in global_alias_norms or norm in canonical_norms:
                        continue
                    db.add(SkillAlias(skill_id=skill.id, alias=alias, alias_normalized=norm))
                    global_alias_norms.add(norm)
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
        for a, b in PARENT:
            add_rel(a, b, SkillRelationType.PARENT_OF)

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
