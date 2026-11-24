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
    # Kullanıcının ilan takibi: "" | saved | applied | hidden
    tracking: Mapped[str] = mapped_column(String(20), default="")
    # Boş değilse kayıt ilan havuzunda saklanır ama değerlendirilmez (kopya, ilan olmayan sayfa, iptal duyurusu).
    archived_reason: Mapped[str] = mapped_column(String(200), default="")
    # Kurumun yayımladığı, bu ilanla kesin eşleştirilemeyen iptal duyurusu (kullanıcı doğrulamalı).
    cancellation_notice: Mapped[str] = mapped_column(String(400), default="")
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
    # OCR ile okunduysa ortalama güven (0-1); normal metin çıkarımında boş
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    # {"P3": 87.6, "P93": 81.2} biçiminde tüm KPSS puanları (JSON)
    kpss_scores: Mapped[str] = mapped_column(Text, default="{}")
    faculty: Mapped[str] = mapped_column(String(200), default="")
    gender: Mapped[str] = mapped_column(String(10), default="")  # "" | Kadın | Erkek
    # Özel statü: "engelli", "eski hükümlü" (virgülle ayrılmış)
    special_status: Mapped[str] = mapped_column(String(100), default="")
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # "" (belirtilmedi) | yapıldı | muaf | tecilli | yapılmadı | yükümlü değil
    military_status: Mapped[str] = mapped_column(String(40), default="")
    # [{"level": "Lisans", "school": "...", "department": "...", "year": 2024}]
    educations: Mapped[str] = mapped_column(Text, default="[]")
    # [{"organization": "...", "position": "...", "start": "2023-01", "end": "2024-06"}]
    experiences: Mapped[str] = mapped_column(Text, default="[]")
    # "" (belirtilmedi) | none (mesleki deneyimim yok) | has
    experience_state: Mapped[str] = mapped_column(String(10), default="")
    foreign_language: Mapped[str] = mapped_column(String(200), default="")
    # {"cities": [], "institution_types": [], "keywords": [], "excluded": []}
    preferences: Mapped[str] = mapped_column(Text, default="{}")
    # Bölümün ilanlarda geçebilecek diğer adları, virgülle ayrılmış
    department_aliases: Mapped[str] = mapped_column(Text, default="")
    preferred_locations: Mapped[str] = mapped_column(String(500), default="Türkiye geneli")
    accepts_shifts: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    yds_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ales_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # "" (doğrulanmadı) | sayisal | sozel | esit_agirlik
    ales_score_type: Mapped[str] = mapped_column(String(20), default="")
    ales_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)  # 4'lük sistem
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


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # new_match | deadline
    kind: Mapped[str] = mapped_column(String(30), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    """Küçük anahtar/değer ayarları (bildirim tercihleri vb.)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# Kullanıcı tabloları: tarama ve yeniden hesaplama bu tablolara dokunmaz.
# ---------------------------------------------------------------------------

class UserSession(Base):
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class UserJobState(Base):
    """Kaydet / başvurdum / sonuç bekleniyor / kazandım / olmadı / ilgilenmiyorum ve notlar."""

    __tablename__ = "user_job_state"

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "" | saved | applied | awaiting | won | lost | hidden
    tracking: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class UserVerification(Base):
    """Kullanıcının elle verdiği uygunluk kararı. Sistem kararından ayrı saklanır ve onu ezer."""

    __tablename__ = "user_verifications"
    __table_args__ = (UniqueConstraint("job_id", "position_id", name="uq_user_verification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    position_id: Mapped[str] = mapped_column(String(120), default="")  # "" = ilanın tamamı
    decision: Mapped[str] = mapped_column(String(20))  # eligible | not_eligible
    note: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[datetime] = mapped_column(DateTime)
    # Karar verildiği andaki ilan içeriği (metin, kadro tablosu, tarihler)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    content_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    job_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobEvent(Base):
    """İlan metninden çıkarılan ya da kullanıcının eklediği/düzenlediği tarihli olay."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    # application_start | application_deadline | exam | interview | result | documents | appointment
    kind: Mapped[str] = mapped_column(String(30))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_time: Mapped[str] = mapped_column(String(5), default="")  # "HH:MM" ya da boş (tüm gün)
    title: Mapped[str] = mapped_column(String(300), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(10), default="auto")  # auto | user
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class UserTask(Base):
    __tablename__ = "user_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    task_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(5), default="")
    end_time: Mapped[str] = mapped_column(String(5), default="")
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # low | normal | high
    # none | daily | weekly | weekdays | monthly
    recurrence: Mapped[str] = mapped_column(String(10), default="none")
    weekdays: Mapped[str] = mapped_column(String(20), default="")  # "0,2,4" (Pazartesi=0)
    until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Tamamlanan günler (ISO tarih listesi, JSON). Tekrarlamayan görevde tek öğe.
    completed_dates: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
# Sonuç takibi
# ---------------------------------------------------------------------------

class ResultAnnouncement(Base):
    """Kurumun resmî sitesinde bulunan sonuç duyurusu. Kayıtlar silinmez; eski aşamalar korunur."""

    __tablename__ = "result_announcements"
    __table_args__ = (UniqueConstraint("job_id", "url", name="uq_result_announcement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    url: Mapped[str] = mapped_column(String(1200))
    title: Mapped[str] = mapped_column(String(500), default="")
    # application | exam | interview | final | list | placement | result
    kind: Mapped[str] = mapped_column(String(20), default="result")
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_url: Mapped[str] = mapped_column(String(1200), default="")
    found_on: Mapped[str] = mapped_column(String(1200), default="")
    # matched | needs_review
    match_status: Mapped[str] = mapped_column(String(20), default="needs_review")
    match_reasons: Mapped[str] = mapped_column(Text, default="[]")
    # "" | confirmed | rejected — kullanıcının kararı; yeniden tarama değiştirmez
    user_decision: Mapped[str] = mapped_column(String(12), default="")
    found_at: Mapped[datetime] = mapped_column(DateTime)


class ResultTracking(Base):
    """İlan başına sonuç takibinin durumu (hangi adres, en son ne zaman, ne oldu)."""

    __tablename__ = "result_tracking"

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(String(1200), default="")
    manual_url: Mapped[str] = mapped_column(String(1200), default="")  # kullanıcının verdiği adres
    # pending | checked | error | no_source
    status: Mapped[str] = mapped_column(String(20), default="pending")
    detail: Mapped[str] = mapped_column(String(500), default="")
    account_only: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Duyuru akışları (YLSY) ve Kariyer Kapısı hesabından aktarılan kayıtlar
# ---------------------------------------------------------------------------

class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("topic", "url", name="uq_announcement_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(30), index=True)  # ylsy
    url: Mapped[str] = mapped_column(String(1200))
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(30), default="")
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[str] = mapped_column(Text, default="[]")  # [{"title","url"}]
    facts: Mapped[str] = mapped_column(Text, default="{}")  # belgeden çıkarılan şartlar ve tarihler
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)


class AccountApplication(Base):
    """Kullanıcının Kariyer Kapısı hesabından kendi oturumuyla aktardığı başvuru/sınav kaydı."""

    __tablename__ = "account_applications"
    __table_args__ = (UniqueConstraint("section", "fingerprint", name="uq_account_application"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section: Mapped[str] = mapped_column(String(20))  # applications | cancelled | exams
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500), default="")
    organization: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(200), default="")
    applied_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exam_time: Mapped[str] = mapped_column(String(5), default="")
    exam_place: Mapped[str] = mapped_column(String(500), default="")
    result: Mapped[str] = mapped_column(String(300), default="")
    raw: Mapped[str] = mapped_column(Text, default="{}")
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # matched | needs_review | unmatched
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
