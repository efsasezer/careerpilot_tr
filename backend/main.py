import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import auth, config
from .database import Base, SessionLocal, engine, get_db
from .document_sync import sync_jobs_documents
from .eligibility import detect_application_status, detect_recruitment_method, parse_kpss_scores
from .events import EVENT_LABELS, task_occurrences
from .matching import build_matches, invalidate_cache, job_content_version
from .migrate import migrate as run_migrations
from .models import (
    CandidateProfile, DocumentPosition, Job, JobDocument, JobEvent, Notification, SourceListing,
    SourceSyncHistory, UserJobState, UserTask, UserVerification,
)
from .notifications import (
    channel_status, load_settings, process_notifications, refresh_daily, save_settings, send_to_channels,
)
from .schemas import (
    BulkJobCreate, EventUpdate, JobCreate, JobRead, LoginRequest, NotificationSettings, ProfileRead,
    ProfileUpdate, TaskCompletion, TaskUpdate, TrackingUpdate, VerificationUpdate,
)
from .sources.registry import get_source_registry
from .sync import (  # noqa: F401  (parse_turkish_date dışa açık)
    cleanup_legacy_rows, download_official_pdf, parse_turkish_date, refetch_job, run_sync, sync_manager,
)

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
    logger.exception("Legacy cleanup failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not config.env_flag("CAREERPILOT_DISABLE_SCHEDULER"):
        sync_manager.start_scheduler()
    yield
    sync_manager.stop_scheduler()


app = FastAPI(
    title="CareerPilot TR API",
    version=config.APP_VERSION,
    description="Kamu personeli alım ilanları, profil eşleştirme ve takip servisi",
    lifespan=lifespan,
)
CORS_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
CORS_ORIGINS.update(
    origin.strip() for origin in os.getenv("CAREERPILOT_CORS_ORIGINS", "").split(",") if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

PUBLIC_PATHS = {"/health", "/auth/login", "/auth/me", "/auth/logout"}


def _client_address(request: Request) -> str:
    """Giriş denemesi sınırı için istemci adresi. Render'da gerçek adres vekil başlığındadır."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and (os.getenv("RENDER") or config.env_flag("CAREERPILOT_TRUST_PROXY")):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        or bool(os.getenv("RENDER"))
    )


@app.middleware("http")
async def require_session(request: Request, call_next):
    """/health ve giriş uçları dışındaki her istek (okuma ve yazma) geçerli oturum ister."""
    path = request.url.path.rstrip("/") or "/"
    if request.method == "OPTIONS" or path in PUBLIC_PATHS:
        return await call_next(request)
    error = auth.config_error()
    if error:
        return JSONResponse(status_code=503, content={"detail": error})
    with SessionLocal() as db:
        authenticated = auth.is_authenticated(db, request.cookies.get(auth.COOKIE_NAME))
    if not authenticated:
        return JSONResponse(status_code=401, content={"detail": "Oturum açmanız gerekiyor."})
    # Çerezli isteklerde siteler arası yazmayı engelle: tarayıcı Origin gönderiyorsa aynı site olmalı.
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD"} and origin:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if origin.split("://", 1)[-1] != host and origin not in CORS_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Bu istek başka bir siteden geldiği için reddedildi."})
    return await call_next(request)


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
    "İlan.gov.tr": {
        "name": "İlan.gov.tr",
        "url": "https://www.ilan.gov.tr/ilan/kategori/44/kamu-personel-alim-ve-sinavlari",
        "description": "Basın İlan Kurumu resmî ilan portalındaki kamu personel alım ve sınav ilanları.",
    },
    "ÖSYM": {
        "name": "ÖSYM",
        "url": "https://www.osym.gov.tr/",
        "description": "KPSS merkezi yerleştirme (tercih) duyuruları. Tercih dönemi açıldığında ilan havuzuna eklenir; kılavuzdaki kadrolar kılavuzdan kontrol edilir.",
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
        "auth_configured": auth.config_error() is None,
    }


# ============================================================
# GİRİŞ / OTURUM
# ============================================================

@app.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    error = auth.config_error()
    if error:
        raise HTTPException(status_code=503, detail=error)
    client = _client_address(request)
    wait = auth.login_limiter.retry_after(client)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla hatalı deneme. {max(1, wait // 60)} dakika sonra yeniden deneyin.",
            headers={"Retry-After": str(wait)},
        )
    if not auth.password_matches(payload.password):
        auth.login_limiter.record_failure(client)
        raise HTTPException(status_code=401, detail="Şifre hatalı.")
    auth.login_limiter.record_success(client)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session(db),
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
        path="/",
    )
    return {"authenticated": True}


@app.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.destroy_session(db, request.cookies.get(auth.COOKIE_NAME))
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"authenticated": False}


@app.get("/auth/me")
def current_session(request: Request, db: Session = Depends(get_db)):
    error = auth.config_error()
    return {
        "authenticated": error is None and auth.is_authenticated(db, request.cookies.get(auth.COOKIE_NAME)),
        "config_error": error,
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
    invalidate_cache()
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
    invalidate_cache()
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


def _public_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job or job.sector != "public":
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    return job


def _event_payload(event: JobEvent) -> dict:
    return {
        "id": event.id,
        "job_id": event.job_id,
        "kind": event.kind,
        "label": event.title or EVENT_LABELS.get(event.kind, "Olay"),
        "date": event.event_date.isoformat(),
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "time": event.event_time,
        "evidence": event.evidence,
        "url": event.url,
        "source": event.source,
        "user_edited": event.user_edited,
        "previous_date": event.previous_date.isoformat() if event.previous_date else None,
    }


@app.get("/jobs/{job_id}/detail")
def job_detail(job_id: int, db: Session = Depends(get_db)):
    """Tek ilanın tam metni, belge incelemesi, tarihli olayları ve kadro bazlı uygunluk sonuçları."""
    job = _public_job(db, job_id)
    positions = build_matches(db, full=True, only_job_ids=[job_id])["jobs"]
    if not positions:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    first = positions[0]
    events = db.scalars(
        select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.deleted.is_(False)).order_by(JobEvent.event_date)
    ).all()
    job_level = db.scalar(select(UserVerification).where(UserVerification.job_id == job_id, UserVerification.position_id == ""))
    return {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "source_name": job.source_name,
        "source_url": job.source_url or None,
        "description": job.description or "",
        "document_review": first.get("document_review"),
        "tracking": first["tracking"],
        "notes": first["notes"],
        "has_pdf": _has_pdf(db, job),
        "events": [_event_payload(event) for event in events],
        "job_verification": first["verification"] if job_level else None,
        "positions": [
            {key: value for key, value in item.items() if key not in ("description", "document_review")}
            for item in positions
        ],
    }


def _has_pdf(db: Session, job: Job) -> bool:
    listing = db.scalar(select(SourceListing).where(SourceListing.job_id == job.id).limit(1))
    if listing is not None and (listing.source_key == "sbb" or ".pdf" in (listing.official_url or "").casefold()):
        return True
    return any(".pdf" in (doc.document_url or "").casefold()
               for doc in db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all())


@app.get("/jobs/{job_id}/document.pdf")
def job_pdf(job_id: int, db: Session = Depends(get_db)):
    """Resmî ilan PDF'ini kaynağından alıp uygulama içinde göstermek için iletir."""
    job = _public_job(db, job_id)
    try:
        body = download_official_pdf(db, job)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Resmî PDF alınamadı: {str(error)[:200]}") from error
    return Response(content=body, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.post("/jobs/{job_id}/ocr")
def retry_reading(job_id: int, db: Session = Depends(get_db)):
    """İlanın belgesini yeniden okur; metin çıkmazsa OCR dener."""
    job = _public_job(db, job_id)
    try:
        result = refetch_job(db, job)
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)[:300]) from error
    invalidate_cache()
    return result


@app.patch("/jobs/{job_id}/tracking")
def update_tracking(job_id: int, payload: TrackingUpdate, db: Session = Depends(get_db)):
    if not db.get(Job, job_id):
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    state = db.get(UserJobState, job_id)
    if state is None:
        state = UserJobState(job_id=job_id, tracking="", notes="", updated_at=datetime.now())
        db.add(state)
    state.tracking = payload.tracking
    if payload.notes is not None:
        state.notes = payload.notes
    state.updated_at = datetime.now()
    db.commit()
    invalidate_cache()
    return {"id": job_id, "tracking": state.tracking, "notes": state.notes}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    if job.source_name not in ("Manuel Giriş", "Toplu Yükleme"):
        raise HTTPException(status_code=409, detail="Kaynaklardan gelen ilanlar silinemez; gizlemek için takip durumunu kullanın.")
    db.delete(job)
    db.commit()
    invalidate_cache()
    return {"deleted": job_id}


# ============================================================
# ELLE DOĞRULAMA
# ============================================================

def _content_version(db: Session, job: Job) -> tuple[str, dict]:
    documents = list(db.scalars(select(JobDocument).where(JobDocument.job_id == job.id).order_by(JobDocument.id)).all())
    rows: dict[int, list] = {}
    if documents:
        for row in db.scalars(
            select(DocumentPosition).where(DocumentPosition.document_id.in_([d.id for d in documents]))
            .order_by(DocumentPosition.document_id, DocumentPosition.row_index)
        ).all():
            rows.setdefault(row.document_id, []).append(row)
    return job_content_version(job, documents, rows)


@app.put("/jobs/{job_id}/verification")
def set_verification(job_id: int, payload: VerificationUpdate, db: Session = Depends(get_db)):
    """Kullanıcının kararı: sistem kararından ayrı saklanır ve her zaman önceliklidir."""
    job = _public_job(db, job_id)
    record = db.scalar(select(UserVerification).where(
        UserVerification.job_id == job_id, UserVerification.position_id == payload.position_id,
    ))
    if record is None:
        record = UserVerification(job_id=job_id, position_id=payload.position_id, decision=payload.decision, verified_at=datetime.now())
        db.add(record)
    content_hash, snapshot = _content_version(db, job)
    record.decision = payload.decision
    record.note = payload.note
    record.verified_at = datetime.now()
    record.content_hash = content_hash
    record.content_snapshot = json.dumps(snapshot, ensure_ascii=False)
    record.job_updated_at = job.updated_at
    db.commit()
    invalidate_cache()
    return {"job_id": job_id, "position_id": record.position_id, "decision": record.decision}


@app.delete("/jobs/{job_id}/verification")
def clear_verification(job_id: int, position_id: str = "", db: Session = Depends(get_db)):
    """Doğrulamayı geri alır; ilan sistemin hesapladığı duruma döner."""
    record = db.scalar(select(UserVerification).where(
        UserVerification.job_id == job_id, UserVerification.position_id == position_id,
    ))
    if record is not None:
        db.delete(record)
        db.commit()
        invalidate_cache()
    return {"job_id": job_id, "position_id": position_id, "decision": None}


@app.post("/jobs/{job_id}/verification/acknowledge")
def acknowledge_update(job_id: int, db: Session = Depends(get_db)):
    """"Gözden geçirdim, karar geçerli": karar değişmez, kayıtlı içerik sürümü güncellenir."""
    job = _public_job(db, job_id)
    content_hash, snapshot = _content_version(db, job)
    records = db.scalars(select(UserVerification).where(UserVerification.job_id == job_id)).all()
    for record in records:
        record.content_hash = content_hash
        record.content_snapshot = json.dumps(snapshot, ensure_ascii=False)
        record.job_updated_at = job.updated_at
    db.commit()
    invalidate_cache()
    return {"job_id": job_id, "acknowledged": len(records)}


# ============================================================
# TAKVİM: İLAN OLAYLARI VE KİŞİSEL GÖREVLER
# ============================================================

@app.get("/calendar")
def calendar(start: date, end: date, db: Session = Depends(get_db)):
    if end < start or (end - start).days > 400:
        raise HTTPException(status_code=422, detail="Geçersiz tarih aralığı.")
    matches = build_matches(db, full=False)
    by_job: dict[int, dict] = {}
    order = {"UYGUN": 0, "POTANSİYEL OLARAK UYGUN": 1, "UYGUN DEĞİL": 2}
    for item in matches["jobs"]:
        current = by_job.get(item["parent_job_id"])
        if current is None or order[item["category"]] < order[current["category"]]:
            by_job[item["parent_job_id"]] = item
    events = db.scalars(select(JobEvent).where(
        JobEvent.deleted.is_(False), JobEvent.event_date <= end,
        func.coalesce(JobEvent.end_date, JobEvent.event_date) >= start,
    ).order_by(JobEvent.event_date, JobEvent.event_time)).all()
    result = []
    for event in events:
        item = by_job.get(event.job_id)
        if item is None or item["tracking"] == "hidden":
            continue
        tracked = item["tracking"] in ("saved", "applied", "awaiting", "won", "lost")
        # Uygun olmayan ilanların olayları takvimi doldurmaz; takip edilenler her zaman görünür.
        if item["category"] == "UYGUN DEĞİL" and not tracked:
            continue
        result.append({
            **_event_payload(event),
            "organization": item["organization"],
            "job_title": item["title"].split(" — ")[0],
            "category": item["category"],
            "tracking": item["tracking"],
            "cancelled": item["application_status"] == "İptal Edildi",
        })
    tasks = db.scalars(select(UserTask)).all()
    return {"events": result, "tasks": task_occurrences(tasks, start, end)}


@app.post("/jobs/{job_id}/events")
def add_event(job_id: int, payload: EventUpdate, db: Session = Depends(get_db)):
    _public_job(db, job_id)
    event = JobEvent(
        job_id=job_id, kind=payload.kind, event_date=payload.event_date, end_date=payload.end_date,
        event_time=payload.event_time, title=payload.title, url=payload.url, source="user", user_edited=True,
        evidence="Kullanıcı tarafından eklendi.", updated_at=datetime.now(),
    )
    db.add(event)
    db.commit()
    return _event_payload(event)


@app.patch("/events/{event_id}")
def edit_event(event_id: int, payload: EventUpdate, db: Session = Depends(get_db)):
    event = db.get(JobEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı")
    event.kind, event.event_date, event.end_date = payload.kind, payload.event_date, payload.end_date
    event.event_time, event.title, event.url = payload.event_time, payload.title, payload.url
    event.user_edited, event.updated_at = True, datetime.now()  # yeniden taramada ezilmez
    db.commit()
    return _event_payload(event)


@app.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(JobEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Olay bulunamadı")
    if event.source == "user":
        db.delete(event)
    else:
        event.deleted, event.user_edited, event.updated_at = True, True, datetime.now()  # tarama geri getirmesin
    db.commit()
    return {"deleted": event_id}


def _task_payload(task: UserTask) -> dict:
    return {
        "id": task.id, "title": task.title, "description": task.description, "task_date": task.task_date.isoformat(),
        "start_time": task.start_time, "end_time": task.end_time, "priority": task.priority, "recurrence": task.recurrence,
        "weekdays": [int(value) for value in (task.weekdays or "").split(",") if value.strip().isdigit()],
        "until": task.until.isoformat() if task.until else None,
        "completed_dates": json.loads(task.completed_dates or "[]"),
    }


def _apply_task(task: UserTask, payload: TaskUpdate) -> None:
    task.title, task.description, task.task_date = payload.title.strip(), payload.description, payload.task_date
    task.start_time, task.end_time, task.priority = payload.start_time, payload.end_time, payload.priority
    task.recurrence, task.until = payload.recurrence, payload.until
    task.weekdays = ",".join(str(day) for day in sorted({day for day in payload.weekdays if 0 <= day <= 6}))


@app.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    return [_task_payload(task) for task in db.scalars(select(UserTask).order_by(UserTask.task_date, UserTask.id)).all()]


@app.post("/tasks")
def create_task(payload: TaskUpdate, db: Session = Depends(get_db)):
    task = UserTask(title="", task_date=payload.task_date, created_at=datetime.now(), completed_dates="[]")
    _apply_task(task, payload)
    db.add(task)
    db.commit()
    return _task_payload(task)


@app.patch("/tasks/{task_id}")
def edit_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(UserTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    _apply_task(task, payload)
    db.commit()
    return _task_payload(task)


@app.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: TaskCompletion, db: Session = Depends(get_db)):
    task = db.get(UserTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    days = set(json.loads(task.completed_dates or "[]"))
    (days.add if payload.done else days.discard)(payload.day.isoformat())
    task.completed_dates = json.dumps(sorted(days))
    db.commit()
    return _task_payload(task)


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(UserTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Görev bulunamadı")
    db.delete(task)
    db.commit()
    return {"deleted": task_id}


# ============================================================
# ADAY PROFİLİ
# ============================================================

_JSON_FIELDS = {"educations": list, "experiences": list, "preferences": dict}


def _profile_payload(profile: CandidateProfile) -> dict:
    data = {column.name: getattr(profile, column.name) for column in CandidateProfile.__table__.columns}
    data["kpss_scores"] = parse_kpss_scores(profile)
    for field, kind in _JSON_FIELDS.items():
        try:
            value = json.loads(data.get(field) or ("[]" if kind is list else "{}"))
        except ValueError:
            value = kind()
        data[field] = value if isinstance(value, kind) else kind()
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
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), background: BackgroundTasks = None):
    """Profili kaydeder. Uygunluk yeniden hesaplanır; elle verilen kararlara dokunulmaz."""
    profile = _get_or_create_profile(db)
    data = payload.model_dump()
    scores = data.pop("kpss_scores")
    if scores is None:  # eski istemci: tek puan türü
        scores = {}
        if data["kpss_p3"] is not None:
            scores[(data["kpss_score_type"] or "P3").strip().upper() or "P3"] = float(data["kpss_p3"])
    for field in _JSON_FIELDS:
        data[field] = json.dumps(data[field], ensure_ascii=False)
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
    """İlan metinlerini ve belge incelemesini de içeren tam yanıt."""
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
    try:
        refresh_daily(db)  # site açıldığında günün bildirimleri hesaplanır
    except Exception:  # pragma: no cover - bildirim hesabı listeyi engellemesin
        db.rollback()
        logger.exception("Daily notification refresh failed")
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
# KAYNAKLAR VE TARAMA
# ============================================================

@app.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    sources_data = []
    for info in SOURCES_STATUS.values():
        job_count = db.scalar(select(func.count(Job.id)).where(
            Job.source_name == info["name"], Job.archived_reason == "",
        )) or 0
        history = db.scalar(
            select(SourceSyncHistory)
            .where(SourceSyncHistory.source_name == info["name"])
            .order_by(SourceSyncHistory.checked_at.desc(), SourceSyncHistory.id.desc())
            .limit(1)
        )
        last_success = db.scalar(
            select(SourceSyncHistory.checked_at)
            .where(SourceSyncHistory.source_name == info["name"], SourceSyncHistory.status.in_(("ok", "partial")))
            .order_by(SourceSyncHistory.checked_at.desc()).limit(1)
        )
        failed = db.execute(
            select(Job.id, Job.title, SourceListing.official_url, SourceListing.status, SourceListing.raw_payload)
            .join(SourceListing, SourceListing.job_id == Job.id)
            .where(Job.source_name == info["name"], SourceListing.status.in_(("detail_failed", "unreadable")), Job.archived_reason == "")
            .limit(25)
        ).all()
        failed_items = []
        for row in failed:
            try:
                reason = json.loads(row.raw_payload or "{}").get("error", "")
            except (ValueError, AttributeError):
                reason = ""
            failed_items.append({
                "job_id": row.id, "title": row.title, "url": row.official_url,
                "scanned": row.status == "unreadable",
                "reason": reason or "İlan ayrıntısı okunamadı.",
            })
        sources_data.append({
            **info,
            "status": (
                "Henüz taranmadı" if not history
                else "Aktif" if history.status == "ok"
                else "Kısmi" if history.status == "partial"
                else "Uyarı" if history.status == "warning"
                else "Hata"
            ),
            "job_count": job_count,
            "last_sync": history.checked_at.isoformat(timespec="seconds") if history else None,
            "last_success": last_success.isoformat(timespec="seconds") if last_success else None,
            "last_found": history.found if history else 0,
            "last_created": history.imported if history else 0,
            "last_updated": history.updated if history else 0,
            "last_unchanged": history.unchanged if history else 0,
            "last_detail_failed": history.detail_failed if history else 0,
            "pages_checked": history.pages_checked if history else 0,
            "last_error": (history.error or None) if history else None,
            "failed_items": failed_items,
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
    """Kaynak taramasını arka planda başlatır; aynı anda ikinci tarama başlamaz."""
    started = sync_manager.start("manual")
    return {"started": started, **sync_manager.status()}


@app.post("/sources/sync-all")
def sync_all_sources(db: Session = Depends(get_db)):
    """Taramayı istek içinde çalıştırır (komut satırı ve testler için). Arayüz /sync kullanır."""
    return run_sync(db, registry=get_source_registry())


@app.post("/documents/sync")
def sync_public_job_documents(db: Session = Depends(get_db)):
    jobs = list(db.scalars(select(Job).where(Job.sector == "public").order_by(Job.id)).all())
    report = sync_jobs_documents(db, jobs)
    db.commit()
    return report


@app.get("/public/summary")
def public_summary(db: Session = Depends(get_db)):
    jobs = list(db.scalars(
        select(Job).where(Job.sector == "public", Job.archived_reason == "").order_by(Job.created_at.desc(), Job.id.desc())
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
    stmt = select(Job).where(Job.sector == "public", Job.archived_reason == "").order_by(Job.created_at.desc(), Job.id.desc())
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
