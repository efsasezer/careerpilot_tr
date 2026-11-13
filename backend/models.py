from datetime import datetime, date
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sector: Mapped[str] = mapped_column(String(20), index=True)  # public / private
    title: Mapped[str] = mapped_column(String(250), index=True)
    organization: Mapped[str] = mapped_column(String(250), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    source_name: Mapped[str] = mapped_column(String(100), default="")  # Kariyer Kapısı, ÖSYM, ...
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(Text, default="")  # comma-separated for v0.1
    kpss_score_type: Mapped[str] = mapped_column(String(30), default="")
    kpss_min_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    education_requirement: Mapped[str] = mapped_column(String(500), default="")
    qualification_codes: Mapped[str] = mapped_column(String(500), default="")
    application_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    application_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    quota: Mapped[str] = mapped_column(String(50), default="")
    recruitment_method: Mapped[str] = mapped_column(String(100), default="")  # KPSS Merkezi / Kurum Sınavı / ...
    is_employment: Mapped[bool] = mapped_column(Boolean, default=True)  # False ise eğitim/burs fırsatı
    status: Mapped[str] = mapped_column(String(40), default="İncelenecek")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())


class CandidateProfile(Base):
    __tablename__ = "candidate_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    degree: Mapped[str] = mapped_column(String(100), default="Lisans")
    department: Mapped[str] = mapped_column(String(200), default="")
    university: Mapped[str] = mapped_column(String(300), default="")
    kpss_score_type: Mapped[str] = mapped_column(String(30), default="P3")
    kpss_p3: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_locations: Mapped[str] = mapped_column(String(500), default="Türkiye geneli")
    accepts_shifts: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    yds_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    driver_license: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_internship: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    internship_description: Mapped[str] = mapped_column(Text, default="")
    certificates: Mapped[str] = mapped_column(Text, default="")
    programming_language_evidence: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())
