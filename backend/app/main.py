from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth as auth_routes
from app.api.v1 import skills as skills_routes
from app.api.v1 import organizations as org_routes
from app.api.v1 import jobs as jobs_routes
from app.api.v1 import documents as documents_routes
from app.api.v1 import questions as questions_routes
from app.api.v1 import assessments as assessments_routes
from app.api.v1 import coding as coding_routes
from app.api.v1 import students as students_routes
from app.api.v1 import applications as applications_routes
from app.api.v1 import evidence as evidence_routes
from app.api.v1 import interviews as interviews_routes
from app.api.v1 import matching as matching_routes
from app.api.v1 import career as career_routes
from app.api.v1 import institutions as institutions_routes
from app.api.v1 import admin as admin_routes
from app.api.v1 import knowledge as knowledge_routes
from app.api.v1 import me as me_routes
from app.api.v1 import dev as dev_routes
from app.api.v1 import opportunities as opportunities_routes
from app.api.v1 import question_imports as question_import_routes
from app.api.v1 import institution_students as institution_students_routes
from app.api.v1 import proctoring as proctoring_routes
from app.api.v1 import hiring_pipeline as hiring_pipeline_routes

app = FastAPI(title="HireAiPro API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, prefix="/api/v1")
app.include_router(skills_routes.router, prefix="/api/v1")
app.include_router(org_routes.router, prefix="/api/v1")
app.include_router(jobs_routes.router, prefix="/api/v1")
app.include_router(documents_routes.router, prefix="/api/v1")
app.include_router(questions_routes.router, prefix="/api/v1")
app.include_router(assessments_routes.router, prefix="/api/v1")
app.include_router(coding_routes.router, prefix="/api/v1")
app.include_router(students_routes.router, prefix="/api/v1")
app.include_router(applications_routes.router, prefix="/api/v1")
app.include_router(evidence_routes.router, prefix="/api/v1")
app.include_router(interviews_routes.router, prefix="/api/v1")
app.include_router(matching_routes.router, prefix="/api/v1")
app.include_router(career_routes.router, prefix="/api/v1")
app.include_router(institutions_routes.router, prefix="/api/v1")
app.include_router(admin_routes.router, prefix="/api/v1")
app.include_router(knowledge_routes.router, prefix="/api/v1")
app.include_router(me_routes.router, prefix="/api/v1")
app.include_router(dev_routes.router, prefix="/api/v1")
app.include_router(question_import_routes.router, prefix="/api/v1")
app.include_router(opportunities_routes.router, prefix="/api/v1")
app.include_router(institution_students_routes.router, prefix="/api/v1")
app.include_router(proctoring_routes.router, prefix="/api/v1")
app.include_router(hiring_pipeline_routes.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}
