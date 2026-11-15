import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import config
from .analysis import skill_frequency
from .database import Base, SessionLocal, engine, get_db
from .document_sync import sync_jobs_documents
from .eligibility import (
    detect_application_status,
    detect_recruitment_method,
    parse_kpss_scores,
)
from .matching import build_matches, invalidate_cache
from .migrate import migrate as run_migrations
from .models import CandidateProfile, Job, Notification, SourceSyncHistory
from .notifications import (
    channel_status,
    load_settings,
    process_notifications,
    save_settings,
    send_to_channels,
)
from .schemas import (
    BulkJobCreate,
    JobCreate,
    JobRead,
    NotificationSettings,
    ProfileRead,
    ProfileUpdate,
    TrackingUpdate,
)
from .sources.registry import get_source_registry
from .sync import cleanup_legacy_rows, parse_turkish_date, run_sync, sync_manager  # noqa: F401  (parse_turkish_date dışa açık)

logger = logging.getLogger(__name__)

# ============================================================
# 1. VERİTABANI VE UYGULAMA BAŞLANGICI
# ============================================================

run_migrations()
Base.metadata.create_all(bind=engine)
try:
    with SessionLocal() as _db:
        cleanup_legacy_rows(_db)
except Exception:  # pragma: no cover - temizlik başarısız olsa da uygulama açılır
    logging.getLogger(__name__).exception("Legacy cleanup failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not config.env_flag("CAREERPILOT_DISABLE_SCHEDULER"):
        sync_manager.start_scheduler()
    yield
    sync_manager.stop_scheduler()


app = FastAPI(
    title="CareerPilot TR API",
    version=config.APP_VERSION,
    description="Kamu personeli alım ilanları, profil eşleştirme ve bildirim servisi",
    lifespan=lifespan,
)
DEMO_MODE = config.is_demo_mode()
CORS_ORIGINS = {
    "https://careerpilot-tr-web.onrender.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
CORS_ORIGINS.update(
    origin.strip()
    for origin in os.getenv("CAREERPILOT_CORS_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def restrict_api(request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path.rstrip("/") or "/"
    # /health herkese açık tek uç noktadır (kişisel veri içermez).
    if path == "/health":
        return await call_next(request)

    access_token = config.access_token()
    if not access_token:
        return JSONResponse(
            status_code=503,
            content={"detail": "Sunucuda erişim anahtarı yapılandırılmamış (CAREERPILOT_ACCESS_TOKEN)."},
        )

    authorization = request.headers.get("authorization", "").strip()
    candidate = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not candidate or not secrets.compare_digest(candidate.encode("utf-8"), access_token.encode("utf-8")):
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={"detail": "Bu veriler için geçerli erişim anahtarı gerekli."},
        )

    if _read_only() and request.method not in {"GET", "HEAD", "OPTIONS"}:
        return JSONResponse(
            status_code=404,
            content={"detail": "Salt okunur yayında veri değiştiren işlemler kullanılamaz."},
        )
    return await call_next(request)


restrict_demo_api = restrict_api  # eski ad


def _read_only() -> bool:
    return DEMO_MODE or config.is_read_only()


SOURCES_STATUS = {
    "SBB Kamu İlanları": {
        "name": "SBB Kamu İlanları",
        "url": "https://kamuilan.sbb.gov.tr/",
        "description": "Strateji ve Bütçe Başkanlığı'nın tüm kamu personel alım ilanlarını yayımladığı resmî portal. İlanların resmî PDF metni okunur.",
    },
    "Kariyer Kapısı": {
        "name": "Kariyer Kapısı",
        "url": "https://kariyerkapisi.gov.tr/isealim",
        "description": "Cumhurbaşkanlığı İnsan Kaynakları Ofisi kamu işe alım platformu.",
    },
    "İŞKUR Kamu Memur Alım İlanları": {
        "name": "İŞKUR Kamu Memur Alım İlanları",
        "url": "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari",
        "description": "İŞKUR'un il bazında yayımladığı kamu memur alım ilanları ve resmî ilan PDF'leri.",
    },
    "Yerel Yönetimler Genel Müdürlüğü": {
        "name": "Yerel Yönetimler Genel Müdürlüğü",
        "url": "https://yerelyonetimler.csb.gov.tr/duyurular",
        "description": "Belediye ve yerel yönetimlerin memur, zabıta ve itfaiye eri alım duyuruları.",
    },
}


def public_application_status(start_date: date | None, end_date: date | None, today: date) -> str:
    return detect_application_status(start_date, end_date, today)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "CareerPilot TR API",
        "version": config.APP_VERSION,
        "demo_mode": DEMO_MODE or config.is_demo_mode(),
        "read_only": _read_only(),
        "auto_sync_hours": 0 if _read_only() else config.sync_interval_hours(),
    }


@app.get("/auth/check")
def check_access():
    return {"authenticated": True}


# ============================================================
# İLAN İŞLEMLERİ
# ============================================================

@app.post("/jobs", response_model=JobRead)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    if not data.get("source_name"):
        data["source_name"] = "Manuel Giriş"
    if not data.get("recruitment_method"):
        data["recruitment_method"] = detect_recruitment_method(data.get("title", ""), data.get("description", ""))
    job = Job(**data)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.post("/jobs/bulk", response_model=list[JobRead])
def create_jobs_bulk(payload: BulkJobCreate, db: Session = Depends(get_db)):
    jobs = []
    for item in payload.jobs:
        data = item.model_dump()
        if not data.get("source_name"):
            data["source_name"] = "Toplu Yükleme"
        if not data.get("recruitment_method"):
            data["recruitment_method"] = detect_recruitment_method(data.get("title", ""), data.get("description", ""))
        jobs.append(Job(**data))
    db.add_all(jobs)
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(
    sector: str | None = Query(default=None, pattern="^(public|private)$"),
    category: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc())
    if sector:
        stmt = stmt.where(Job.sector == sector)
    if category:
        stmt = stmt.where(Job.category == category)
    return list(db.scalars(stmt).all())


@app.get("/jobs/{job_id}/detail")
def job_detail(job_id: int, db: Session = Depends(get_db)):
    """Tek ilanın tam metni, belge incelemesi ve pozisyon bazlı uygunluk sonuçları."""
    job = db.get(Job, job_id)
    if not job or job.sector != "public":
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    positions = [item for item in build_matches(db, full=True, only_job_ids=[job_id])["jobs"]]
    if not positions:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    first = positions[0]
    return {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "source_name": job.source_name,
        "source_url": job.source_url or None,
        "description": job.description or "",
        "document_review": first.get("document_review"),
        "tracking": job.tracking or "",
        "notes": job.notes or "",
        "positions": [
            {key: value for key, value in item.items() if key not in ("description", "document_review")}
            for item in positions
        ],
    }


@app.patch("/jobs/{job_id}/tracking")
def update_tracking(job_id: int, payload: TrackingUpdate, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    job.tracking = payload.tracking
    if payload.notes is not None:
        job.notes = payload.notes
    job.updated_at = datetime.now()
    db.commit()
    invalidate_cache()
    return {"id": job.id, "tracking": job.tracking, "notes": job.notes}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    if job.source_name not in ("Manuel Giriş", "Toplu Yükleme"):
        raise HTTPException(status_code=409, detail="Kaynaklardan gelen ilanlar silinemez; gizlemek için takip durumunu kullanın.")
    db.delete(job)
    db.commit()
    return {"deleted": job_id}


# ============================================================
# ADAY PROFİLİ
# ============================================================

def _profile_payload(profile: CandidateProfile) -> dict:
    data = {column.name: getattr(profile, column.name) for column in CandidateProfile.__table__.columns}
    data["kpss_scores"] = parse_kpss_scores(profile)
    return data


def _get_or_create_profile(db: Session) -> CandidateProfile:
    profile = db.get(CandidateProfile, 1)
    if not profile:
        profile = CandidateProfile(id=1, degree="", department="", kpss_score_type="", kpss_scores="{}")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@app.get("/profile", response_model=ProfileRead)
def get_profile(db: Session = Depends(get_db)):
    return ProfileRead(**_profile_payload(_get_or_create_profile(db)))


def _refresh_notifications() -> None:
    try:
        with SessionLocal() as db:
            process_notifications(db)
    except Exception:  # pragma: no cover
        logger.exception("Notification refresh failed")


@app.put("/profile", response_model=ProfileRead)
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    background: BackgroundTasks = None,
):
    profile = _get_or_create_profile(db)
    data = payload.model_dump()
    scores = data.pop("kpss_scores")
    if scores is None:  # eski istemci: tek puan türü
        scores = {}
        if data["kpss_p3"] is not None:
            scores[(data["kpss_score_type"] or "P3").strip().upper() or "P3"] = float(data["kpss_p3"])
    for key, value in data.items():
        setattr(profile, key, value)
    primary = "P3" if "P3" in scores else (max(scores, key=scores.get) if scores else "")
    profile.kpss_scores = json.dumps(scores, ensure_ascii=False)
    profile.kpss_score_type = primary
    profile.kpss_p3 = scores.get(primary)
    profile.updated_at = datetime.now()
    db.commit()
    db.refresh(profile)
    invalidate_cache()
    if background is not None:
        background.add_task(_refresh_notifications)
    return ProfileRead(**_profile_payload(profile))


# ============================================================
# EŞLEŞTİRME
# ============================================================

@app.get("/matches")
def matches(db: Session = Depends(get_db)):
    """Profil eşleştirme sonuçları (uzun metinler olmadan; ayrıntı için /jobs/{id}/detail)."""
    return build_matches(db, full=False)


@app.get("/public/matches")
def public_matches(db: Session = Depends(get_db)):
    """Eski istemcilerle uyumlu, ilan metinlerini de içeren tam yanıt."""
    return build_matches(db, full=True)


# ============================================================
# BİLDİRİMLER
# ============================================================

def _notification_payload(item: Notification) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "job_id": item.job_id,
        "category": item.category,
        "title": item.title,
        "body": item.body,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "read": item.read_at is not None,
    }


@app.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    unread = db.scalar(select(func.count(Notification.id)).where(Notification.read_at.is_(None))) or 0
    return {"unread": unread, "items": [_notification_payload(item) for item in db.scalars(stmt).all()]}


@app.post("/notifications/read-all")
def read_all_notifications(db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.read_at.is_(None)).values(read_at=datetime.now()))
    db.commit()
    return {"unread": 0}


@app.post("/notifications/test")
def test_notification(db: Session = Depends(get_db)):
    settings = load_settings(db)
    results = send_to_channels(
        settings,
        "CareerPilot TR: test bildirimi",
        "Bildirim kanalınız çalışıyor. Yeni eşleşen ilanlar ve yaklaşan son başvurular buraya gönderilecek.",
    )
    if not results:
        raise HTTPException(status_code=400, detail="Etkin bir e-posta veya Telegram kanalı yok. Önce ayarları kaydedin.")
    return {"channels": results}


@app.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db)):
    item = db.get(Notification, notification_id)
    if not item:
        raise HTTPException(status_code=404, detail="Bildirim bulunamadı")
    if item.read_at is None:
        item.read_at = datetime.now()
        db.commit()
    return _notification_payload(item)


@app.get("/notifications/settings")
def get_notification_settings(db: Session = Depends(get_db)):
    return {**load_settings(db).model_dump(), **channel_status()}


@app.put("/notifications/settings")
def put_notification_settings(payload: NotificationSettings, db: Session = Depends(get_db)):
    return {**save_settings(db, payload).model_dump(), **channel_status()}


# ============================================================
# KAYNAKLAR VE SENKRONİZASYON
# ============================================================

@app.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    sources_data = []
    for info in SOURCES_STATUS.values():
        job_count = db.scalar(select(func.count(Job.id)).where(Job.source_name == info["name"])) or 0
        history = db.scalar(
            select(SourceSyncHistory)
            .where(SourceSyncHistory.source_name == info["name"])
            .order_by(SourceSyncHistory.checked_at.desc(), SourceSyncHistory.id.desc())
            .limit(1)
        )
        sources_data.append({
            **info,
            "status": (
                "Henüz taranmadı" if not history
                else "Aktif" if history.status == "ok"
                else "Kısmi" if history.status == "partial"
                else "Hata"
            ),
            "job_count": job_count,
            "last_sync": history.checked_at.isoformat(timespec="seconds") if history else None,
            "last_found": history.found if history else 0,
            "last_created": history.imported if history else 0,
            "last_updated": history.updated if history else 0,
            "last_detail_failed": history.detail_failed if history else 0,
            "pages_checked": history.pages_checked if history else 0,
            "last_error": (history.error or None) if history else None,
        })
    return sources_data


@app.get("/sources/status")
def sources_status(db: Session = Depends(get_db)):
    return list_sources(db=db)


@app.get("/sync/status")
def sync_status():
    return sync_manager.status()


@app.post("/sync", status_code=202)
def start_sync():
    """Kaynak taramasını arka planda başlatır; ilerleme /sync/status ile izlenir."""
    started = sync_manager.start("manual")
    return {"started": started, **sync_manager.status()}


@app.post("/sources/sync-all")
def sync_all_sources(db: Session = Depends(get_db)):
    """Taramayı istek içinde çalıştırır (komut satırı ve testler için). Arayüz /sync kullanır."""
    return run_sync(db, registry=get_source_registry())


@app.post("/sources/kariyer-kapisi/sync")
def sync_kariyer_kapisi(db: Session = Depends(get_db)):
    """Eski arayüzle uyumluluk: yalnızca Kariyer Kapısı kaynağını tarar."""
    from .sync import sync_source

    report = sync_source(db, "kariyer-kapisi", get_source_registry()["kariyer-kapisi"])
    report.pop("touched_job_ids", None)
    process_notifications(db)
    return {**report, "created": report["imported"]}


@app.post("/documents/sync")
def sync_public_job_documents(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.sector == "public").order_by(Job.id)).all())
    report = sync_jobs_documents(db, jobs)
    db.commit()
    return report


@app.get("/public/summary")
def public_summary(db: Session = Depends(get_db)):
    jobs = list(db.scalars(
        select(Job).where(Job.sector == "public").order_by(Job.created_at.desc(), Job.id.desc())
    ).all())
    today = date.today()
    recent_cutoff = datetime.now() - timedelta(days=7)
    open_count = upcoming_count = recent_count = 0
    latest = []
    for job in jobs:
        status = public_application_status(job.application_start, job.application_deadline, today)
        upcoming_count += status == "Başvuru Başlamadı"
        open_count += status == "Başvuru Açık"
        recent_count += bool(job.created_at and job.created_at >= recent_cutoff)
        if len(latest) < 8:
            latest.append(_listing_payload(job, status))
    return {
        "total": len(jobs),
        "open": open_count,
        "upcoming": upcoming_count,
        "new_last_7_days": recent_count,
        "last_updated": max((job.updated_at or job.created_at for job in jobs if job.updated_at or job.created_at), default=None),
        "latest": latest,
    }


def _listing_payload(job: Job, status: str) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "city": job.city or None,
        "source_name": job.source_name or "Kaynak belirtilmemiş",
        "source_url": job.source_url or None,
        "application_start": job.application_start.isoformat() if job.application_start else None,
        "announcement_date": job.announcement_date.isoformat() if job.announcement_date else None,
        "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
        "application_status": status,
        "recruitment_method": job.recruitment_method or None,
        "employment_type": job.employment_type or None,
        "quota": job.quota or None,
        "kpss_score_type": job.kpss_score_type or None,
    }


@app.get("/public/listings")
def public_listings(
    q: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Job).where(Job.sector == "public").order_by(Job.created_at.desc(), Job.id.desc())
    if source:
        stmt = stmt.where(Job.source_name == source)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            Job.title.ilike(term) | Job.organization.ilike(term) | Job.city.ilike(term) | Job.description.ilike(term)
        )
    today = date.today()
    matching = []
    for job in db.scalars(stmt).all():
        application_status = public_application_status(job.application_start, job.application_deadline, today)
        if status and application_status != status:
            continue
        matching.append(_listing_payload(job, application_status))
    return {"total": len(matching), "items": matching[offset:offset + limit]}


# ============================================================
# ÖZEL SEKTÖR BECERİ ANALİZİ (eski Streamlit arayüzü)
# ============================================================

@app.get("/analytics/skills")
def analyze_skills(category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Job).where(Job.sector == "private")
    if category:
        stmt = stmt.where(Job.category == category)
    jobs = list(db.scalars(stmt).all())
    records = [{"title": j.title, "skills": j.skills, "description": j.description} for j in jobs]
    return {
        "category": category or "Tüm özel sektör ilanları",
        "job_count": len(jobs),
        "skills": skill_frequency(records),
    }
