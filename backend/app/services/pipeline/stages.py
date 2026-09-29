"""Stage vocabulary and ordering rules for the job hiring pipeline. Pure functions, no I/O."""

APTITUDE = "APTITUDE_ASSESSMENT"
TECHNICAL = "TECHNICAL_ASSESSMENT"
CODING = "CODING_ASSESSMENT"
TECH_INTERVIEW = "TECHNICAL_INTERVIEW"
HR_INTERVIEW = "HR_INTERVIEW"

ASSESSMENT_STAGES = (APTITUDE, TECHNICAL, CODING)
INTERVIEW_STAGES = (TECH_INTERVIEW, HR_INTERVIEW)
ALL_STAGES = ASSESSMENT_STAGES + INTERVIEW_STAGES

LABELS = {
    APTITUDE: "Aptitude Assessment",
    TECHNICAL: "Technical Assessment",
    CODING: "Coding Assessment",
    TECH_INTERVIEW: "Technical Interview",
    HR_INTERVIEW: "HR Interview",
}

# Stage progress statuses
LOCKED, AVAILABLE, IN_PROGRESS, COMPLETED, SKIPPED = "LOCKED", "AVAILABLE", "IN_PROGRESS", "COMPLETED", "SKIPPED"
DONE = (COMPLETED, SKIPPED)

# Defaults used the first time a job's pipeline is read (this is also the behaviour of every pre-pipeline job).
DEFAULTS = {
    APTITUDE: {"enabled": False, "duration_minutes": 30, "question_count": 15},
    TECHNICAL: {"enabled": True, "duration_minutes": 40, "question_count": 12},
    CODING: {"enabled": False, "duration_minutes": 60, "question_count": 2},
    TECH_INTERVIEW: {"enabled": True, "duration_minutes": 45, "question_count": 8},
    HR_INTERVIEW: {"enabled": False, "duration_minutes": 20, "question_count": 6},
}

APTITUDE_CATEGORIES = ["Quantitative Aptitude", "Logical Reasoning", "Analytical Reasoning", "Data Interpretation", "Verbal Ability"]
HR_CATEGORIES = ["communication", "collaboration", "conflict handling", "motivation", "career goals", "work preferences", "availability and logistics"]
HR_CATEGORY_LABELS = {"communication": "Communication", "collaboration": "Team collaboration", "conflict handling": "Conflict handling",
                      "motivation": "Motivation for the role", "career goals": "Career goals", "work preferences": "Work preferences",
                      "availability and logistics": "Availability and logistics"}
CODING_LANGUAGES = ["python", "javascript", "cpp"]


class PipelineError(Exception):
    pass


def label(stage_type: str) -> str:
    return LABELS.get(stage_type, stage_type)


def is_assessment(stage_type: str) -> bool:
    return stage_type in ASSESSMENT_STAGES


def is_interview(stage_type: str) -> bool:
    return stage_type in INTERVIEW_STAGES


def validate_order(stage_types: list[str]) -> None:
    """Assessment stages must precede interview stages; stages may be reordered within each group. This rules out states such as
    'HR completed -> assessment pending'. Unknown or duplicate types are rejected."""
    if len(set(stage_types)) != len(stage_types):
        raise PipelineError("A stage can appear only once in a pipeline")
    for t in stage_types:
        if t not in ALL_STAGES:
            raise PipelineError(f"Unknown stage type {t}")
    seen_interview = False
    for t in stage_types:
        if is_interview(t):
            seen_interview = True
        elif seen_interview:
            raise PipelineError("Assessment stages must come before interview stages")


def question_domain_problem(stage_type: str | None, q) -> str | None:
    """Why a question may not be used in an assessment of this stage (None = fine). Aptitude, technical and coding content stay separate."""
    domain = getattr(q, "domain", None) or "TECHNICAL"
    qtype = str(getattr(q, "question_type", "") or "")
    if domain in ("HR_INTERVIEW", "TECHNICAL_INTERVIEW"):
        return "Interview questions cannot be used in an assessment"
    if stage_type == APTITUDE:
        return None if domain == "APTITUDE" else "Only aptitude questions can be added to the Aptitude Assessment"
    if domain == "APTITUDE":
        return "Aptitude questions can only be used in the Aptitude Assessment"
    if stage_type == CODING:
        return None if qtype.endswith("CODING") else "Only coding problems can be added to the Coding Assessment"
    if stage_type == TECHNICAL and qtype.endswith("CODING"):
        return "Coding problems belong in the Coding Assessment"
    return None
