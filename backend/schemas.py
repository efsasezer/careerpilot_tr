from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    sector: str = Field(pattern="^(public|private)$")
    title: str = Field(min_length=2, max_length=250)
    organization: str = ""
    category: str = ""
    city: str = ""
    source_url: str = ""
    source_name: str = ""
    description: str = ""
    skills: str = ""
    kpss_score_type: str = ""
    kpss_min_score: float | None = None
    education_requirement: str = ""
    qualification_codes: str = ""
    application_start: date | None = None
    application_deadline: date | None = None
    quota: str = ""
    recruitment_method: str = ""
    is_employment: bool = True
    status: str = "İncelenecek"
    notes: str = ""


class JobRead(JobCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    degree: str = "Lisans"
    department: str = ""
    university: str = ""
    kpss_score_type: str = "P3"
    kpss_p3: float | None = None
    preferred_locations: str = "Türkiye geneli"
    accepts_shifts: bool | None = None
    yds_score: float | None = None
    age: int | None = None
    driver_license: bool | None = None
    experience_years: float | None = None
    has_internship: bool | None = None
    internship_description: str = ""
    certificates: str = ""
    programming_language_evidence: str = ""
    skills: str = ""
    notes: str = ""


class ProfileRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime | None = None


class BulkJobCreate(BaseModel):
    jobs: list[JobCreate]
