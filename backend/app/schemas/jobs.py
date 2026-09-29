import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import JobStatus, RequirementType
from app.services.jobs.posting import PostingError, to_absolute, validate_posting


class JobPostingIn(BaseModel):
    """Posting details. Everything is optional at creation; a job cannot be published without employment type, work mode and (on-site/hybrid) location.
    Money is entered in `compensation_input_unit` (ABSOLUTE amount, or LPA for INR per year) and stored as an absolute amount."""
    employment_type: str | None = None
    work_mode: str | None = None
    location_city: str | None = Field(default=None, max_length=120)
    location_state: str | None = Field(default=None, max_length=120)
    location_country: str | None = Field(default=None, max_length=120)
    experience_level: str | None = None
    experience_min_years: int | None = Field(default=None, ge=0, le=60)
    experience_max_years: int | None = Field(default=None, ge=0, le=60)
    number_of_openings: int | None = None
    application_deadline: dt.datetime | None = None
    compensation_currency: str | None = None
    compensation_min: Decimal | None = None
    compensation_max: Decimal | None = None
    compensation_period: str | None = None
    compensation_type: str | None = None
    compensation_input_unit: Literal["ABSOLUTE", "LPA"] = "ABSOLUTE"
    internship_duration_value: int | None = None
    internship_duration_unit: str | None = None
    conversion_guaranteed: bool = False
    conversion_notes: str | None = Field(default=None, max_length=1000)
    full_time_compensation_min: Decimal | None = None
    full_time_compensation_max: Decimal | None = None
    full_time_input_unit: Literal["ABSOLUTE", "LPA"] = "ABSOLUTE"

    @model_validator(mode="after")
    def _check(self):
        try:
            self.columns()
        except PostingError as exc:
            raise ValueError(str(exc)) from exc
        return self

    def columns(self) -> dict:
        """Validated, normalized column values (absolute amounts)."""
        v = self.model_dump(include=set(JobPostingIn.model_fields) - {"compensation_input_unit", "full_time_input_unit"})
        for k in ("location_city", "location_state", "location_country", "conversion_notes"):
            v[k] = (v[k] or "").strip() or None
        cur = (v["compensation_currency"] or "").upper() or None
        v["compensation_currency"] = cur
        v["compensation_min"] = to_absolute(v["compensation_min"], self.compensation_input_unit, cur, v["compensation_period"])
        v["compensation_max"] = to_absolute(v["compensation_max"], self.compensation_input_unit, cur, v["compensation_period"])
        v["full_time_compensation_min"] = to_absolute(v["full_time_compensation_min"], self.full_time_input_unit, cur, "YEAR")
        v["full_time_compensation_max"] = to_absolute(v["full_time_compensation_max"], self.full_time_input_unit, cur, "YEAR")
        return validate_posting(v)


class JobCreate(JobPostingIn):
    title: str
    description_raw: str | None = None
    location: str | None = None  # legacy free text; superseded by location_city/state/country


class JobSkillOut(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID | None
    raw_skill_name: str
    requirement_type: RequirementType
    minimum_level: float
    importance: float
    evidence_text: str | None
    extraction_confidence: float
    confirmed: bool
    canonical_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str | None = None
    title: str
    description_raw: str | None
    status: JobStatus
    location: str | None
    employment_type: str | None
    work_mode: str | None = None
    location_city: str | None = None
    location_state: str | None = None
    location_country: str | None = None
    experience_level: str | None = None
    experience_min_years: int | None = None
    experience_max_years: int | None = None
    number_of_openings: int | None = None
    application_deadline: dt.datetime | None = None
    compensation_currency: str | None = None
    compensation_min: Decimal | None = None
    compensation_max: Decimal | None = None
    compensation_period: str | None = None
    compensation_type: str | None = None
    internship_duration_value: int | None = None
    internship_duration_unit: str | None = None
    conversion_guaranteed: bool = False
    conversion_notes: str | None = None
    full_time_compensation_min: Decimal | None = None
    full_time_compensation_max: Decimal | None = None
    display: dict | None = None  # computed strings (compensation, duration, location...) shared by every view
    distribution_type: str = "OPEN_MARKET"
    institution_approval: str = "NOT_REQUIRED"
    target_institution_id: uuid.UUID | None = None
    target_institution_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JobWithSkillsOut(JobOut):
    skills: list[JobSkillOut] = []


class JobSkillUpdate(BaseModel):
    id: uuid.UUID | None = None
    skill_id: uuid.UUID | None = None
    raw_skill_name: str
    requirement_type: RequirementType
    minimum_level: float
    importance: float
    delete: bool = False


class ConfirmRequirementsRequest(BaseModel):
    skills: list[JobSkillUpdate]


class ExtractedJobSkill(BaseModel):
    raw_skill_name: str
    requirement_type: Literal["required", "preferred"]
    minimum_level: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    evidence_text: str
    extraction_confidence: float = Field(ge=0, le=1)


class ExtractedJobSkills(BaseModel):
    skills: list[ExtractedJobSkill]
