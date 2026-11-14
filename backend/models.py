from datetime import datetime, date
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    announcement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quota: Mapped[str] = mapped_column(String(50), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    recruitment_method: Mapped[str] = mapped_column(String(100), default="")  # KPSS Merkezi / Kurum Sınavı / ...
    is_employment: Mapped[bool] = mapped_column(Boolean, default=True)  # False ise eğitim/burs fırsatı
    status: Mapped[str] = mapped_column(String(40), default="İncelenecek")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, onupdate=func.now())


class SourceListing(Base):
    __tablename__ = "source_listings"
    __table_args__ = (
        UniqueConstraint("source_key", "external_id", name="uq_source_listing_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    source_key: Mapped[str] = mapped_column(String(80), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    official_url: Mapped[str] = mapped_column(String(1200))
    list_hash: Mapped[str] = mapped_column(String(64), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    raw_payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(40), default="pending_detail")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SourceSyncHistory(Base):
    __tablename__ = "source_sync_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), index=True)
    source_name: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30))
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    pages_checked: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    detail_failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")


class JobDocumentScan(Base):
    __tablename__ = "job_document_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="not_scanned")
    attachments_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class JobDocument(Base):
    __tablename__ = "job_documents"
    __table_args__ = (
        UniqueConstraint("job_id", "document_url", name="uq_job_document_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    document_url: Mapped[str] = mapped_column(String(1200))
    title: Mapped[str] = mapped_column(String(500), default="")
    content_type: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(40), default="discovered")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    parsed_content_hash: Mapped[str] = mapped_column(String(64), default="")
    etag: Mapped[str] = mapped_column(String(500), default="")
    last_modified: Mapped[str] = mapped_column(String(200), default="")
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    shared_requirements: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DocumentPosition(Base):
    __tablename__ = "document_positions"
    __table_args__ = (
        UniqueConstraint("document_id", "row_index", name="uq_document_position_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("job_documents.id"), index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    position_title: Mapped[str] = mapped_column(String(250), default="")
    education_requirement: Mapped[str] = mapped_column(Text, default="")
    quota: Mapped[str] = mapped_column(String(100), default="")
    kpss_score_type: Mapped[str] = mapped_column(String(50), default="")
    kpss_min_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    city: Mapped[str] = mapped_column(String(500), default="")
    qualification_codes: Mapped[str] = mapped_column(String(500), default="")
    written_exam_invite_text: Mapped[str] = mapped_column(Text, default="")
    written_exam_invite_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requirements_text: Mapped[str] = mapped_column(Text, default="")
    raw_cells: Mapped[str] = mapped_column(Text, default="{}")


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
