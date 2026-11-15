from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    announcement_date: date | None = None
    quota: str = ""
    employment_type: str = ""
    recruitment_method: str = ""
    is_employment: bool = True
    status: str = "İncelenecek"
    notes: str = ""


class JobRead(JobCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracking: str = ""
    archived_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BulkJobCreate(BaseModel):
    jobs: list[JobCreate]


class TrackingUpdate(BaseModel):
    tracking: str = Field(default="", pattern="^(|saved|applied|hidden)$")
    notes: str | None = Field(default=None, max_length=5000)


class ProfileUpdate(BaseModel):
    degree: str = Field(default="Lisans", max_length=100)
    department: str = Field(default="", max_length=200)
    department_aliases: str = Field(default="", max_length=1000)
    faculty: str = Field(default="", max_length=200)
    gender: str = Field(default="", pattern="^(|Kadın|Erkek)$")
    special_status: str = Field(default="", max_length=100)
    university: str = Field(default="", max_length=300)
    # Geriye dönük uyumluluk: tek puan türü/puanı. Yeni istemciler kpss_scores gönderir.
    kpss_score_type: str = Field(default="P3", max_length=30)
    kpss_p3: float | None = Field(default=None, ge=0, le=100)
    kpss_scores: dict[str, float] | None = None
    preferred_locations: str = Field(default="Türkiye geneli", max_length=500)
    accepts_shifts: bool | None = None
    yds_score: float | None = Field(default=None, ge=0, le=100)
    age: int | None = Field(default=None, ge=15, le=80)
    driver_license: bool | None = None
    experience_years: float | None = Field(default=None, ge=0, le=60)
    has_internship: bool | None = None
    internship_description: str = ""
    certificates: str = ""
    programming_language_evidence: str = ""
    skills: str = ""
    notes: str = ""

    @field_validator("kpss_scores")
    @classmethod
    def _validate_scores(cls, value):
        if value is None:
            return value
        cleaned = {}
        for key, score in value.items():
            name = str(key).strip().upper().replace("KPSS", "").replace(" ", "").replace("-", "")
            if not name.startswith("P") or not name[1:].isdigit():
                raise ValueError(f"Geçersiz KPSS puan türü: {key}")
            if not 0 <= float(score) <= 100:
                raise ValueError(f"{name} puanı 0-100 arasında olmalı")
            cleaned[name] = float(score)
        return cleaned


class ProfileRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kpss_scores: dict[str, float] = {}
    updated_at: datetime | None = None


class NotificationSettings(BaseModel):
    notify_categories: list[str] = ["UYGUN", "POTANSİYEL OLARAK UYGUN"]
    only_preferred_locations: bool = False
    deadline_reminder_days: int = Field(default=3, ge=0, le=30)
    email_enabled: bool = False
    email_to: str = Field(default="", max_length=200)
    telegram_enabled: bool = False
    telegram_chat_id: str = Field(default="", max_length=60)

    @field_validator("notify_categories")
    @classmethod
    def _validate_categories(cls, value):
        allowed = {"UYGUN", "POTANSİYEL OLARAK UYGUN"}
        return [item for item in dict.fromkeys(value) if item in allowed]

    @field_validator("email_to")
    @classmethod
    def _validate_email(cls, value):
        value = value.strip()
        if value and ("@" not in value or " " in value or "\n" in value):
            raise ValueError("Geçerli bir e-posta adresi girin")
        return value
