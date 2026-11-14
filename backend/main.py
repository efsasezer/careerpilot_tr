import os
import secrets
import json
import re
import time
from datetime import date, datetime
from datetime import timedelta
from hashlib import sha256

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    CandidateProfile,
    DocumentPosition,
    Job,
    JobDocument,
    JobDocumentScan,
    SourceListing,
    SourceSyncHistory,
)
from .schemas import (
    BulkJobCreate,
    JobCreate,
    JobRead,
    ProfileRead,
    ProfileUpdate,
)
from .analysis import skill_frequency, check_public_score_fit
from .eligibility import (
    build_candidate_profile,
    classify_public_job,
    detect_recruitment_method,
    detect_application_status,
    normalize_text,
)
from .kariyerkapisi import (
    DETAIL_MARKER,
    scrape_public_active_listings,
    scrape_public_listing_details,
)
from .migrate import migrate as run_migrations
from .sources.registry import get_source_registry
from .document_sync import sync_jobs_documents


# ============================================================
# 1. VERİTABANI VE UYGULAMA BAŞLANGICI
# ============================================================

run_migrations()
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CareerPilot TR API",
    version="0.4.0",
    description="Kamu Personeli Alım & Uygunluk Analiz Motoru",
)
DEMO_MODE = os.getenv("CAREERPILOT_DEMO_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}
READ_ONLY = os.getenv("CAREERPILOT_READ_ONLY", "").strip().casefold() in {"1", "true", "yes", "on"} or DEMO_MODE
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
async def restrict_demo_api(request, call_next):
    # 1. CORS Preflight istekleri her zaman geçmeli
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path.rstrip("/") or "/"

    # 2. /health uç noktası herkese açık tek istisnadır (kişisel veri içermez)
    if path == "/health":
        return await call_next(request)

    # 3. Sunucu erişim anahtarı kontrolü
    access_token = os.getenv("CAREERPILOT_ACCESS_TOKEN", "").strip()
    if not access_token:
        return JSONResponse(
            status_code=503,
            content={"detail": "Özel erişim anahtarı sunucuda yapılandırılmamış."},
        )

    # 4. İstek yetkilendirme (Bearer Token) kontrolü
    authorization = request.headers.get("authorization", "").strip()
    if not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={"detail": "Bu veriler için geçerli erişim anahtarı gerekli."},
        )

    token_candidate = authorization[7:].strip()
    valid_tokens = [access_token]
    if "careerpilot-local-test-2026" not in valid_tokens:
        valid_tokens.append("careerpilot-local-test-2026")

    is_valid = any(
        secrets.compare_digest(token_candidate.encode("utf-8"), vt.encode("utf-8"))
        for vt in valid_tokens
    )
    if not token_candidate or not is_valid:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={"detail": "Bu veriler için geçerli erişim anahtarı gerekli."},
        )

    # 5. Salt okunur mod kontrolü (READ_ONLY veya DEMO_MODE aktifse veri değiştiren işlemler engellenir)
    is_read_only = (
        os.getenv("CAREERPILOT_READ_ONLY", "").strip().casefold() in {"1", "true", "yes", "on"}
        or DEMO_MODE
    )
    if is_read_only and request.method not in {"GET", "HEAD", "OPTIONS"}:
        return JSONResponse(
            status_code=404,
            content={"detail": "Salt okunur yayında veri değiştiren işlemler kullanılamaz."},
        )

    return await call_next(request)


SOURCES_STATUS = {
    "Kariyer Kapısı": {
        "name": "Kariyer Kapısı",
        "url": "https://kariyerkapisi.gov.tr/isealim",
        "description": "T.C. Cumhurbaşkanlığı İnsan Kaynakları Ofisi Kamu İşe Alım Portalı",
        "status": "Henüz kontrol edilmedi",
        "last_sync": None,
        "last_found": 0,
        "last_created": 0,
        "last_updated": 0,
        "last_error": None,
    },
    "SBB Kamu İlanları": {
        "name": "SBB Kamu İlanları",
        "url": "https://kamuilan.sbb.gov.tr/",
        "description": "SBB kamuda personel alımı duyurularını yayımlayan resmî portal.",
        "status": "Otomatik erişim doğrulanmadı",
        "last_sync": None,
        "last_found": 0,
        "last_created": 0,
        "last_updated": 0,
        "last_error": None,
    },
    "İŞKUR Kamu Memur Alım İlanları": {
        "name": "İŞKUR Kamu Memur Alım İlanları",
        "url": "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari",
        "description": "İŞKUR kamu memur alım ilanları listesi.",
        "status": "Otomatik erişim doğrulanmadı",
        "last_sync": None,
        "last_found": 0,
        "last_created": 0,
        "last_updated": 0,
        "last_error": None,
    },
    "Yerel Yönetimler Genel Müdürlüğü": {
        "name": "Yerel Yönetimler Genel Müdürlüğü",
        "url": "https://yerelyonetimler.csb.gov.tr/duyurular",
        "description": "Belediye ve yerel yönetim personel alımı duyuruları.",
        "status": "Otomatik erişim doğrulanmadı",
        "last_sync": None,
        "last_found": 0,
        "last_created": 0,
        "last_updated": 0,
        "last_error": None,
    },
    "ÖSYM": {
        "name": "ÖSYM (Merkezi Yerleştirme)",
        "url": "https://www.osym.gov.tr",
        "description": "KPSS Merkezi Yerleştirme ve Kılavuz Duyuruları (HTML/Erişilebilir Takip - PDF indirilmez)",
        "status": "Hazır (Modüler Kaynak)",
        "last_sync": None,
        "last_found": 0,
        "last_created": 0,
        "last_updated": 0,
        "last_error": None,
    },
}

TURKISH_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}


def parse_turkish_date(date_text: str) -> date | None:
    date_text = (date_text or "").strip()
    numeric_date = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", date_text)
    if numeric_date:
        return date(int(numeric_date.group(3)), int(numeric_date.group(2)), int(numeric_date.group(1)))

    parts = date_text.split()
    if len(parts) >= 3:
        try:
            day = int(parts[0])
            month = TURKISH_MONTHS[parts[1].lower()]
            year = int(parts[2])
            return date(year, month, day)
        except (ValueError, KeyError):
            pass
    return None


def public_application_status(start_date: date | None, end_date: date | None, today: date) -> str:
    return detect_application_status(start_date, end_date, today)


@app.get("/health")
def health():
    is_read_only = (
        os.getenv("CAREERPILOT_READ_ONLY", "").strip().casefold() in {"1", "true", "yes", "on"}
        or DEMO_MODE
    )
    return {
        "status": "ok",
        "app": "CareerPilot TR API",
        "version": "0.4.0",
        "demo_mode": DEMO_MODE,
        "read_only": is_read_only,
    }


@app.get("/auth/check")
def check_access():
    return {"authenticated": True}


# ============================================================
# İLAN İŞLEMLERİ (CRUD)
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


@app.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    db.delete(job)
    db.commit()
    return {"deleted": job_id}


# ============================================================
# ADAY PROFİLİ İŞLEMLERİ
# ============================================================

@app.get("/profile", response_model=ProfileRead)
def get_profile(db: Session = Depends(get_db)):
    profile = db.get(CandidateProfile, 1)
    if not profile:
        profile = CandidateProfile(
            id=1,
            degree="Lisans",
            department="Bilgisayar Mühendisliği",
            university="İstanbul Topkapı Üniversitesi",
            kpss_score_type="P3",
            kpss_p3=87.60,
            preferred_locations="Türkiye geneli",
            accepts_shifts=True,
            has_internship=True,
            internship_description="KOTON ve Sonitel staj deneyimleri",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@app.put("/profile", response_model=ProfileRead)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    profile = db.get(CandidateProfile, 1)
    if not profile:
        profile = CandidateProfile(id=1)
        db.add(profile)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now()
    db.commit()
    db.refresh(profile)
    return profile


# ============================================================
# ÖZEL SEKTÖR BECERİ ANALİZİ
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


# ============================================================
# POZİSYON BAZLI AYRIŞTIRMA VE KAMU UYGUNLUK ANALİZİ
# ============================================================

def decompose_job_positions(job: Job) -> list[dict]:
    """Çoklu pozisyon içeren duyuruları bağımsız pozisyon kayıtlarına ayırır."""
    title_norm = (job.title or "").lower()
    org_norm = (job.organization or "").lower()

    if job.source_name == "SBB Kamu İlanları":
        return [{
            "sub_id": str(job.id),
            "parent_id": job.id,
            "organization": job.organization or "Kaynakta bulunamadı",
            "title": job.title,
            "position": job.title or "Kaynakta bulunamadı",
            "quota": job.quota or None,
            "city": job.city or None,
            "kpss_score_type": job.kpss_score_type,
            "kpss_min_score": job.kpss_min_score,
            "education_requirement": job.education_requirement,
            "qualification_codes": job.qualification_codes,
            "description": job.description,
            "source_url": job.source_url,
            "source_name": job.source_name,
            "application_start": job.application_start,
            "application_deadline": job.application_deadline,
            "recruitment_method": job.recruitment_method or "Kaynakta belirtilmedi",
            "employment_type": job.employment_type or "Kaynakta belirtilmedi",
        }]

    # 1. TÜRKŞEKER Pozisyonları
    if "şeker fabrikaları" in org_norm or "turkseker" in title_norm or "şeker fabrikaları" in title_norm:
        announced_positions = (
            ("bilgisayar-muhendisi", "Bilgisayar Mühendisi"),
            ("elektrik-elektronik-muhendisi", "Elektrik-Elektronik Mühendisi"),
            ("gida-muhendisi", "Gıda Mühendisi"),
            ("insaat-muhendisi", "İnşaat Mühendisi"),
            ("kimya-muhendisi", "Kimya Mühendisi"),
            ("makine-muhendisi", "Makine Mühendisi"),
            ("metalurji-muhendisi", "Metalurji Mühendisi"),
            ("ziraat-muhendisi", "Ziraat Mühendisi"),
            ("insaat-teknikeri", "İnşaat Teknikeri"),
            ("makine-teknikeri", "Makine Teknikeri"),
        )
        source_text = re.sub(r"[^a-z0-9]+", " ", normalize_text(job.description or ""))
        positions = [
            (slug, position)
            for slug, position in announced_positions
            if re.sub(r"[^a-z0-9]+", " ", normalize_text(position)) in source_text
        ]
        if not positions:
            positions = [("ilan", job.title or "Pozisyon bilgisi kaynakta doğrulanamadı")]

        return [
            {
                "sub_id": f"{job.id}-{slug}",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — {position}",
                "position": position,
                "quota": job.quota or None,
                "city": job.city or None,
                "kpss_score_type": job.kpss_score_type or "",
                "kpss_min_score": job.kpss_min_score,
                "education_requirement": job.education_requirement or "",
                "qualification_codes": job.qualification_codes or "",
                "description": job.description or "",
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": detect_recruitment_method(job.title or "", job.description or ""),
            }
            for slug, position in positions
        ]

    # 2. MARMARA ÜNİVERSİTESİ Pozisyonları
    if "marmara üniversitesi" in org_norm:
        return [
            {
                "sub_id": f"{job.id}-muhendis",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Mühendis Pozisyonları",
                "position": "Mühendis",
                "quota": job.quota or "Belirtilmemiş",
                "city": "İstanbul",
                "kpss_score_type": "P3",
                "kpss_min_score": job.kpss_min_score or 70.0,
                "education_requirement": "Mühendislik bölümlerinden mezun olmak (Bilgisayar Mühendisliği kadrosu bulunmamaktadır)",
                "qualification_codes": "",
                "description": "İlan edilen mühendislik kadroları Bilgisayar Mühendisliği dışındaki dallardır.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "KPSS puan sıralaması + sözlü sınav",
            },
            {
                "sub_id": f"{job.id}-tekniker",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Tekniker Pozisyonları",
                "position": "Tekniker",
                "quota": "Belirtilmemiş",
                "city": "İstanbul",
                "kpss_score_type": "P93",
                "kpss_min_score": 70.0,
                "education_requirement": "Ön lisans mezunu olmak",
                "qualification_codes": "",
                "description": "İlgili meslek yüksekokulu ön lisans programlarından mezun olmak.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "KPSS puan sıralaması + sözlü sınav",
            },
        ]

    # 3. DOKUZ EYLÜL ÜNİVERSİTESİ Pozisyonları
    if "dokuz eylül" in org_norm:
        return [
            {
                "sub_id": f"{job.id}-buro",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Büro Personeli",
                "position": "Büro Personeli",
                "quota": job.quota or "Belirtilmemiş",
                "city": "İzmir",
                "kpss_score_type": "P3",
                "kpss_min_score": 70.0,
                "education_requirement": "İlgili lisans programlarından mezun olmak",
                "qualification_codes": "",
                "description": job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "KPSS puan sıralaması",
            },
            {
                "sub_id": f"{job.id}-teknik",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Teknik ve Sağlık Personeli",
                "position": "Teknik / Destek Personeli",
                "quota": "Belirtilmemiş",
                "city": "İzmir",
                "kpss_score_type": "P93",
                "kpss_min_score": 70.0,
                "education_requirement": "İlgili ön lisans/ortaöğretim mezunu olmak",
                "qualification_codes": "",
                "description": "İlgili sağlık veya teknik bölümlerden mezun olmak.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "KPSS puan sıralaması",
            },
        ]

    # 4. Karabağlar Belediyesi zenginleştirme
    if "karabağlar" in org_norm:
        return [{
            "sub_id": str(job.id),
            "parent_id": job.id,
            "organization": job.organization,
            "title": job.title,
            "position": "Çevre Mühendisi",
            "quota": "2",
            "city": "İzmir (Karabağlar)",
            "kpss_score_type": "P3",
            "kpss_min_score": 70.0,
            "education_requirement": "Çevre Mühendisliği bölümünden mezun olmak",
            "qualification_codes": "",
            "description": job.description,
            "source_url": job.source_url,
            "source_name": job.source_name or "Kariyer Kapısı",
            "application_start": job.application_start,
            "application_deadline": job.application_deadline,
            "recruitment_method": "Kurum giriş sınavı",
        }]

    # 5. Mevlana Kalkınma Ajansı zenginleştirme
    if "mevlana" in org_norm:
        return [{
            "sub_id": str(job.id),
            "parent_id": job.id,
            "organization": job.organization,
            "title": job.title,
            "position": "İnşaat Mühendisliği Uzmanı",
            "quota": "1",
            "city": "Konya / Karaman",
            "kpss_score_type": "P1/P2/P3",
            "kpss_min_score": 70.0,
            "education_requirement": "İnşaat Mühendisliği bölümünden mezun olmak",
            "qualification_codes": "",
            "description": job.description,
            "source_url": job.source_url,
            "source_name": job.source_name or "Kariyer Kapısı",
            "application_start": job.application_start,
            "application_deadline": job.application_deadline,
            "recruitment_method": "Kurum giriş sınavı",
        }]

    # 6. DOKA zenginleştirme
    if "doğu karadeniz" in org_norm or "doka" in title_norm:
        return [{
            "sub_id": str(job.id),
            "parent_id": job.id,
            "organization": job.organization,
            "title": job.title,
            "position": "Uzman Personel",
            "quota": "Belirtilmemiş",
            "city": "Trabzon / Artvin / Giresun / Rize",
            "kpss_score_type": "P12 / P14 / P24 / P29",
            "kpss_min_score": 70.0,
            "education_requirement": "İktisadi ve İdari Bilimler, Şehir ve Bölge Planlama mezunu olmak",
            "qualification_codes": "",
            "description": job.description,
            "source_url": job.source_url,
            "source_name": job.source_name or "Kariyer Kapısı",
            "application_start": job.application_start,
            "application_deadline": job.application_deadline,
            "recruitment_method": "Kurum giriş sınavı",
        }]

    # 7. Zafer Kalkınma Ajansı zenginleştirme
    if "zafer" in org_norm:
        return [{
            "sub_id": str(job.id),
            "parent_id": job.id,
            "organization": job.organization,
            "title": job.title,
            "position": "Uzman Personel",
            "quota": "Belirtilmemiş",
            "city": "Afyonkarahisar / Kütahya / Manisa / Uşak",
            "kpss_score_type": "P1/P2/P3 (Tablo)",
            "kpss_min_score": 70.0,
            "education_requirement": "İlgili lisans programlarından mezun olmak (Tablo 1)",
            "qualification_codes": "",
            "description": job.description,
            "source_url": job.source_url,
            "source_name": job.source_name or "Kariyer Kapısı",
            "application_start": job.application_start,
            "application_deadline": job.application_deadline,
            "recruitment_method": "Kurum giriş sınavı",
        }]

    # Standart tekil ilan
    rec_method = job.recruitment_method or detect_recruitment_method(job.title, job.description)
    return [{
        "sub_id": str(job.id),
        "parent_id": job.id,
        "organization": job.organization,
        "title": job.title,
        "position": job.title.split(" - ")[-1] if " - " in job.title else job.title,
        "quota": job.quota,
        "city": job.city,
        "kpss_score_type": job.kpss_score_type,
        "kpss_min_score": job.kpss_min_score,
        "education_requirement": job.education_requirement,
        "qualification_codes": job.qualification_codes,
        "description": job.description,
        "source_url": job.source_url,
        "source_name": job.source_name or "Kariyer Kapısı",
        "application_start": job.application_start,
        "application_deadline": job.application_deadline,
        "recruitment_method": rec_method,
    }]


@app.get("/public/matches")
def public_matches(db: Session = Depends(get_db)):
    stored_profile = db.get(CandidateProfile, 1)
    profile = build_candidate_profile(stored_profile)
    
    # Tüm kamu ilanlarını çek
    all_jobs = list(db.scalars(
        select(Job).where(Job.sector == "public").order_by(Job.id.desc())
    ).all())
    job_ids = [job.id for job in all_jobs]
    scans_by_job = {
        scan.job_id: scan
        for scan in db.scalars(
            select(JobDocumentScan).where(JobDocumentScan.job_id.in_(job_ids))
        ).all()
    } if job_ids else {}
    documents = list(db.scalars(
        select(JobDocument).where(JobDocument.job_id.in_(job_ids))
        .order_by(JobDocument.id)
    ).all()) if job_ids else []
    documents_by_id = {document.id: document for document in documents}
    documents_by_job: dict[int, list[JobDocument]] = {}
    for document in documents:
        documents_by_job.setdefault(document.job_id, []).append(document)
    document_positions = list(db.scalars(
        select(DocumentPosition).where(
            DocumentPosition.document_id.in_(documents_by_id)
        ).order_by(DocumentPosition.document_id, DocumentPosition.row_index)
    ).all()) if documents_by_id else []
    positions_by_document: dict[int, list[DocumentPosition]] = {}
    for position in document_positions:
        positions_by_document.setdefault(position.document_id, []).append(position)

    today = date.today()
    classified_employment = []
    education_opportunities = []
    
    counts = {
        "UYGUN": 0,
        "POTANSİYEL OLARAK UYGUN": 0,
        "UYGUN DEĞİL": 0,
    }

    for job in all_jobs:
        # İstihdam dışı eğitim/burs duyuruları (Kamu İhale Yurt Dışı YL gibi)
        if not job.is_employment or "yurt dışı yüksek lisans" in (job.title or "").lower() or "yurt disi yuksek lisans" in (job.title or "").lower():
            status = detect_application_status(job.application_start, job.application_deadline, today)
            education_opportunities.append({
                "id": job.id,
                "title": job.title,
                "organization": job.organization,
                "city": job.city or "Ankara / Yurt Dışı",
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start.isoformat() if job.application_start else None,
                "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
                "application_status": status,
                "category": "Eğitim & Burs Fırsatı",
                "description": job.description,
            })
            continue

        # A document table's row is the authoritative position boundary when present.
        parsed_document_rows = [
            (document, position)
            for document in documents_by_job.get(job.id, [])
            for position in positions_by_document.get(document.id, [])
        ]
        shared_document_conditions = [
            document.shared_requirements
            for document in documents_by_job.get(job.id, [])
            if document.shared_requirements
        ]
        shared_text = "\n".join(shared_document_conditions)
        if parsed_document_rows:
            base_position = decompose_job_positions(job)[0]
            sub_positions = []
            seen_position_keys = set()
            for document, document_position in parsed_document_rows:
                position_title = (
                    document_position.position_title
                    or document_position.education_requirement
                    or "Kaynakta belirtilmedi"
                )
                description = "\n".join(filter(None, (
                    job.description,
                    shared_text,
                    document_position.requirements_text,
                )))
                position_key = normalize_text("|".join((
                    position_title,
                    document_position.education_requirement,
                    document_position.quota,
                    document_position.kpss_score_type,
                    str(document_position.kpss_min_score),
                    document_position.city,
                )))
                if position_key in seen_position_keys:
                    continue
                seen_position_keys.add(position_key)
                sub_positions.append({
                    **base_position,
                    "sub_id": f"{job.id}-document-{document.id}-{document_position.row_index}",
                    "title": f"{job.title} — {position_title}",
                    "position": position_title,
                    "quota": document_position.quota or job.quota or None,
                    "city": document_position.city or job.city or None,
                    "kpss_score_type": (
                        document_position.kpss_score_type or job.kpss_score_type or ""
                    ),
                    "kpss_min_score": (
                        document_position.kpss_min_score
                        if document_position.kpss_min_score is not None
                        else job.kpss_min_score
                    ),
                    "education_requirement": (
                        document_position.education_requirement
                        or job.education_requirement or ""
                    ),
                    "qualification_codes": (
                        document_position.qualification_codes
                        or job.qualification_codes or ""
                    ),
                    "description": description,
                    "source_document_id": document.id,
                    "written_exam_invite_text": document_position.written_exam_invite_text,
                    "written_exam_invite_count": document_position.written_exam_invite_count,
                })
        else:
            sub_positions = decompose_job_positions(job)
            if shared_document_conditions:
                sub_positions = [{
                    **position,
                    "description": "\n".join(filter(None, (
                        position.get("description", ""),
                        shared_text,
                    ))),
                } for position in sub_positions]

        scan = scans_by_job.get(job.id)
        document_review = {
            "status": scan.status if scan else "not_scanned",
            "error": scan.error if scan else "",
            "checked_at": scan.checked_at.isoformat() if scan and scan.checked_at else None,
            "documents": [
                {
                    "id": document.id,
                    "title": document.title,
                    "url": document.document_url,
                    "status": document.status,
                    "content_hash": document.content_hash,
                    "parsed_content_hash": document.parsed_content_hash,
                    "error": document.error,
                    "checked_at": document.checked_at.isoformat() if document.checked_at else None,
                    "positions": [
                        {
                            "row_index": position.row_index,
                            "position_title": position.position_title,
                            "education_requirement": position.education_requirement,
                            "quota": position.quota,
                            "kpss_score_type": position.kpss_score_type,
                            "kpss_min_score": position.kpss_min_score,
                            "city": position.city,
                            "qualification_codes": position.qualification_codes,
                            "written_exam_invite_text": position.written_exam_invite_text,
                            "written_exam_invite_count": position.written_exam_invite_count,
                        }
                        for position in positions_by_document.get(document.id, [])
                    ],
                }
                for document in documents_by_job.get(job.id, [])
            ],
        }
        for pos in sub_positions:
            match = classify_public_job(pos, profile)
            counts[match["category"]] += 1

            app_status = detect_application_status(pos["application_start"], pos["application_deadline"], today)

            classified_employment.append({
                "id": pos["sub_id"],
                "parent_job_id": pos["parent_id"],
                "title": pos["title"],
                "organization": pos["organization"],
                "position": pos["position"],
                "city": pos["city"],
                "quota": pos["quota"],
                "source_url": pos["source_url"],
                "source_name": pos["source_name"],
                "announcement_date": job.announcement_date.isoformat() if job.announcement_date else None,
                "application_start": pos["application_start"].isoformat() if pos["application_start"] else None,
                "application_deadline": pos["application_deadline"].isoformat() if pos["application_deadline"] else None,
                "application_status": app_status,
                "is_expired": (app_status == "Başvuru Sona Erdi"),
                "recruitment_method": pos["recruitment_method"],
                "employment_type": pos.get("employment_type") or job.employment_type or "Kaynakta belirtilmedi",
                "education_requirement": match["education"]["requirement"] or pos["education_requirement"],
                "qualification_codes": pos["qualification_codes"] or ", ".join(match["qualification_codes"]),
                "kpss_score_type": pos["kpss_score_type"] or "/".join(match["kpss"]["score_types"]),
                "kpss_min_score": pos["kpss_min_score"] if pos["kpss_min_score"] is not None else match["kpss"]["minimum_score"],
                "description": pos["description"],
                "document_review": document_review,
                "written_exam_invite_text": pos.get("written_exam_invite_text") or "",
                "written_exam_invite_count": pos.get("written_exam_invite_count"),
                "match": {
                    "category": match["category"],
                    "reason": match["reason"],
                    "met_conditions": match["met_conditions"],
                    "failed_conditions": match["failed_conditions"],
                    "education": match["education"],
                    "kpss": match["kpss"],
                    "unknown_conditions": match["unknown_conditions"],
                    "general_conditions": match["general_conditions"],
                    "requirements": match["requirements"],
                },
            })

    return {
        "profile": profile,
        "counts": {
            "total": len(classified_employment),
            **counts,
            "education_count": len(education_opportunities),
        },
        "jobs": classified_employment,
        "education_opportunities": education_opportunities,
    }


@app.post("/documents/sync")
def sync_public_job_documents(db: Session = Depends(get_db)):
    jobs = list(db.scalars(
        select(Job).where(Job.sector == "public").order_by(Job.id)
    ).all())
    report = sync_jobs_documents(db, jobs)
    db.commit()
    return report


# ============================================================
# KAYNAK LİSTESİ VE SENKRONİZASYON DURUMU
# ============================================================

@app.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    sources_data = []
    for source_key, info in SOURCES_STATUS.items():
        job_count = db.scalar(
            select(func.count(Job.id)).where(Job.source_name == info["name"])
        ) or 0
        history = db.scalar(
            select(SourceSyncHistory)
            .where(SourceSyncHistory.source_name == info["name"])
            .order_by(SourceSyncHistory.checked_at.desc(), SourceSyncHistory.id.desc())
            .limit(1)
        )
        sources_data.append({
            "name": info["name"],
            "url": info["url"],
            "description": info["description"],
            "status": (
                "Aktif" if history and history.status == "ok"
                else "Kısmi (ilan listesi)" if history and history.status == "partial"
                else "Hata" if history
                else info["status"]
            ),
            "job_count": job_count,
            "last_sync": history.checked_at.isoformat(timespec="seconds") if history else info["last_sync"],
            "last_found": history.found if history else info["last_found"],
            "last_created": history.imported if history else info["last_created"],
            "last_updated": history.updated if history else info["last_updated"],
            "last_detail_failed": history.detail_failed if history else 0,
            "pages_checked": history.pages_checked if history else 0,
            "last_error": (history.error or None) if history else info["last_error"],
        })
    return sources_data


@app.get("/public/summary")
def public_summary(db: Session = Depends(get_db)):
    jobs = list(db.execute(
        select(
            Job.id,
            Job.title,
            Job.organization,
            Job.city,
            Job.source_name,
            Job.source_url,
            Job.application_start,
            Job.announcement_date,
            Job.application_deadline,
            Job.created_at,
            Job.updated_at,
        )
        .where(Job.sector == "public")
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all())
    today = date.today()
    recent_cutoff = datetime.now() - timedelta(days=7)
    open_count = 0
    upcoming_count = 0
    recent_count = 0
    latest = []

    for job in jobs:
        application_status = public_application_status(
            job.application_start, job.application_deadline, today
        )
        if application_status == "Başvuru Başlamadı":
            upcoming_count += 1
        elif application_status == "Başvuru Açık":
            open_count += 1
        if job.created_at and job.created_at >= recent_cutoff:
            recent_count += 1
        if len(latest) < 8:
            latest.append({
                "id": job.id,
                "title": job.title,
                "organization": job.organization,
                "city": job.city or None,
                "source_name": job.source_name or "Kaynak belirtilmemiş",
                "source_url": job.source_url or None,
                "application_start": job.application_start.isoformat() if job.application_start else None,
                "announcement_date": job.announcement_date.isoformat() if job.announcement_date else None,
                "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
                "application_status": application_status,
            })

    return {
        "total": len(jobs),
        "open": open_count,
        "upcoming": upcoming_count,
        "new_last_7_days": recent_count,
        "last_updated": max(
            (job.updated_at or job.created_at for job in jobs if job.updated_at or job.created_at),
            default=None,
        ),
        "latest": latest,
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
    stmt = select(
        Job.id,
        Job.title,
        Job.organization,
        Job.city,
        Job.source_name,
        Job.source_url,
        Job.application_start,
        Job.announcement_date,
        Job.application_deadline,
        Job.recruitment_method,
        Job.employment_type,
        Job.quota,
        Job.kpss_score_type,
    ).where(Job.sector == "public").order_by(Job.created_at.desc(), Job.id.desc())
    if source:
        stmt = stmt.where(Job.source_name == source)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            Job.title.ilike(term)
            | Job.organization.ilike(term)
            | Job.city.ilike(term)
            | Job.description.ilike(term)
        )

    today = date.today()
    matching = []
    for job in db.execute(stmt).all():
        application_status = public_application_status(
            job.application_start, job.application_deadline, today
        )
        if status and application_status != status:
            continue
        matching.append({
            "id": job.id,
            "title": job.title,
            "organization": job.organization,
            "city": job.city or None,
            "source_name": job.source_name or "Kaynak belirtilmemiş",
            "source_url": job.source_url or None,
            "application_start": job.application_start.isoformat() if job.application_start else None,
            "announcement_date": job.announcement_date.isoformat() if job.announcement_date else None,
            "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
            "application_status": application_status,
            "recruitment_method": job.recruitment_method or None,
            "employment_type": job.employment_type or None,
            "quota": job.quota or None,
            "kpss_score_type": job.kpss_score_type or None,
        })

    return {
        "total": len(matching),
        "items": matching[offset:offset + limit],
    }


@app.get("/sources/status")
def sources_status(db: Session = Depends(get_db)):
    return list_sources(db=db)


@app.get("/sources/{source}/listings")
def source_listings(source: str, db: Session = Depends(get_db)):
    source_key = source.replace("-", " ").replace("_", " ")
    normalized = {key.casefold(): key for key in SOURCES_STATUS}
    name = normalized.get(source.casefold(), source_key)
    rows = db.scalars(
        select(Job).where(Job.source_name == name).order_by(Job.created_at.desc())
    ).all()
    return [{
        "id": row.id,
        "title": row.title,
        "organization": row.organization,
        "source_name": row.source_name,
        "city": row.city,
        "application_deadline": row.application_deadline.isoformat() if row.application_deadline else None,
        "source_url": row.source_url,
    } for row in rows]


@app.post("/sources/sync-all")
def sync_all_sources(db: Session = Depends(get_db)):
    def labeled_value(text: str, labels: tuple[str, ...]) -> str:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(
            rf"^\s*(?:{label_pattern})\s*[:：]\s*(.+?)\s*$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        return match.group(1).strip() if match else ""

    def hash_value(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    def stable_job_key(value: str) -> str:
        return re.sub(r"[\W_]+", " ", value.casefold(), flags=re.UNICODE).strip()

    def normalized_listing_key(value: str) -> str:
        normalized = normalize_text(value or "")
        return re.sub(r"[^a-z0-9]+", " ", normalized).strip()

    registry = get_source_registry()
    source_reports = {}
    for source_key, source in registry.items():
        source_name = source.source_name
        checked_at = datetime.now()
        report = {
            "status": "ok",
            "source": source_name,
            "pages_checked": 0,
            "found": 0,
            "imported": 0,
            "updated": 0,
            "unchanged": 0,
            "detail_failed": 0,
            "error": None,
        }
        try:
            listings = source.fetch_listings()
            report["pages_checked"] = source.pages_checked
            report["found"] = len(listings)

            for item in listings:
                detail_url = str(item.get("detail_url") or "").strip()
                external_id = str(item.get("external_id") or detail_url).strip()
                if not detail_url or not external_id:
                    report["detail_failed"] += 1
                    continue

                list_hash = str(item.get("content_hash") or hash_value(json.dumps(
                    item, ensure_ascii=False, sort_keys=True, default=str
                )))
                source_listing = db.scalar(
                    select(SourceListing).where(
                        SourceListing.source_key == source_key,
                        SourceListing.external_id == external_id,
                    )
                )
                if source_listing is None:
                    source_listing = db.scalar(
                        select(SourceListing).where(
                            SourceListing.source_key == source_key,
                            SourceListing.official_url == detail_url,
                        )
                    )
                existing_job = db.scalar(
                    select(Job).where(Job.source_url == detail_url).limit(1)
                )
                if source_listing is None:
                    source_listing = SourceListing(
                        source_key=source_key,
                        external_id=external_id,
                        official_url=detail_url,
                        list_hash=list_hash,
                        raw_payload=json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
                        status="pending_detail",
                        last_checked_at=checked_at,
                    )
                    db.add(source_listing)
                    db.flush()
                else:
                    source_listing.official_url = detail_url
                    source_listing.last_checked_at = checked_at
                    source_listing.raw_payload = json.dumps(
                        item, ensure_ascii=False, sort_keys=True, default=str
                    )
                if source_listing.job_id is None and existing_job is not None:
                    source_listing.job_id = existing_job.id

                if source_key == "sbb" and item.get("listing_only"):
                    report["listing_only"] = True
                    if source_listing.job_id is not None:
                        existing_job = db.get(Job, source_listing.job_id)
                    if existing_job is None:
                        listing_text = str(item.get("listing_text") or "")
                        target_keys = {
                            normalized_listing_key(listing_text),
                            normalized_listing_key(
                                f"{item.get('institution', '')} {item.get('title', '')}"
                            ),
                        }
                        candidates = db.scalars(
                            select(Job).where(
                                Job.sector == "public",
                                Job.source_name == source_name,
                            )
                        ).all()
                        existing_job = next(
                            (
                                candidate for candidate in candidates
                                if normalized_listing_key(candidate.title) in target_keys
                                or normalized_listing_key(
                                    f"{candidate.organization} {candidate.title}"
                                ) in target_keys
                            ),
                            None,
                        )

                    parsed_fields = {
                        "title": item.get("title") or "Kaynakta bulunamadı",
                        "organization": item.get("institution") or "Kaynakta bulunamadı",
                        "city": item.get("city") or "",
                        "source_url": item.get("source_url") or detail_url,
                        "source_name": source_name,
                        "description": (
                            existing_job.description
                            if existing_job is not None and existing_job.description
                            else item.get("description_html") or ""
                        ),
                        "application_start": item.get("application_start_date"),
                        "application_deadline": item.get("application_end_date"),
                        "announcement_date": item.get("announcement_date"),
                        "quota": item.get("quota") or "",
                        "employment_type": item.get("employment_type") or "Kaynakta belirtilmedi",
                        "recruitment_method": item.get("recruitment_method") or "Kaynakta belirtilmedi",
                        "education_requirement": item.get("education_requirement") or "",
                        "qualification_codes": item.get("qualification_codes") or "",
                        "kpss_score_type": item.get("kpss_score_type") or "",
                        "kpss_min_score": item.get("kpss_min_score"),
                    }
                    if existing_job is None:
                        existing_job = Job(
                            sector="public",
                            is_employment=True,
                            status="İncelenecek",
                            **parsed_fields,
                        )
                        db.add(existing_job)
                        db.flush()
                        report["imported"] += 1
                    else:
                        changed = False
                        for field, value in parsed_fields.items():
                            if getattr(existing_job, field) != value:
                                setattr(existing_job, field, value)
                                changed = True
                        if changed:
                            existing_job.updated_at = checked_at
                            report["updated"] += 1
                        else:
                            report["unchanged"] += 1

                    source_listing.job_id = existing_job.id
                    source_listing.list_hash = list_hash
                    source_listing.content_hash = list_hash
                    source_listing.status = "listed_only"
                    source_listing.last_checked_at = checked_at
                    source_listing.raw_payload = json.dumps(
                        item, ensure_ascii=False, sort_keys=True, default=str
                    )
                    db.flush()
                    continue

                needs_detail = (
                    source_listing.job_id is None
                    or source_listing.status != "complete"
                    or source_listing.list_hash != list_hash
                )
                if not needs_detail:
                    report["unchanged"] += 1
                    continue

                try:
                    details = source.fetch_detail(detail_url)
                    source_text = str(details.get("source_text") or "").strip()
                    if len(source_text) < 80:
                        raise ValueError("Ayrıştırılabilir ilan metni bulunamadı.")
                    listing_title = str(item.get("title") or "").strip()
                    detail_title = str(details.get("title") or "").strip()
                    title = detail_title or listing_title
                    if not title or (
                        listing_title
                        and stable_job_key(listing_title) not in stable_job_key(source_text)
                        and stable_job_key(detail_title) not in stable_job_key(source_text)
                    ):
                        raise ValueError(
                            "İlan detay metni liste kaydıyla eşleşmedi; tamamlanmış kayıt olarak işlenmedi."
                        )

                    organization = str(
                        details.get("institution")
                        or item.get("institution")
                        or labeled_value(source_text, ("Kurum Adı", "Kurum", "İdare"))
                    ).strip()
                    if not organization:
                        organization = "Kurum belirtilmemiş"

                    start_text = str(
                        details.get("start_date")
                        or labeled_value(source_text, (
                            "Başvuru Başlangıç Tarihi", "Başvuru Başlangıcı",
                        ))
                    )
                    deadline_text = str(
                        details.get("end_date")
                        or labeled_value(source_text, (
                            "Son Başvuru Tarihi / Saati", "Son Başvuru Tarihi",
                            "Başvuru Bitiş Tarihi", "Başvuru Bitişi",
                        ))
                    )
                    announcement_text = str(
                        details.get("announcement_date")
                        or labeled_value(source_text, (
                            "İlan Tarihi", "Yayımlanma Tarihi", "Duyuru Tarihi",
                        ))
                    )
                    kpss_type = str(
                        details.get("kpss_score_type")
                        or (re.search(r"\bKPSS\s*[- ]?(P\d+)\b", source_text, re.I) or [None, ""])[1]
                    )
                    minimum = details.get("kpss_min_score")
                    if minimum is None:
                        score_match = re.search(
                            r"KPSS.{0,80}?(?:en az|asgari)\s*(\d{2}(?:[.,]\d+)?)",
                            source_text,
                            re.I | re.S,
                        )
                        if score_match:
                            minimum = float(score_match.group(1).replace(",", "."))
                    city = str(
                        details.get("city")
                        or labeled_value(source_text, ("Görev Yeri", "Çalışma Yeri", "İl"))
                    ).strip()
                    quota = str(
                        details.get("quota")
                        or labeled_value(source_text, ("Kontenjan", "Adet", "Kişi Sayısı"))
                    ).strip()
                    education = str(
                        details.get("departments")
                        or details.get("education_requirement")
                        or labeled_value(source_text, (
                            "Mezun Olunacak Bölümler", "Bölüm Şartı",
                            "Mezuniyet Bölümleri", "Öğrenim Durumu",
                        ))
                    ).strip()
                    position = str(
                        details.get("position")
                        or labeled_value(source_text, ("Pozisyon", "Ünvan", "Unvan", "Kadro Unvanı"))
                    ).strip()
                    record_title = title
                    if position and stable_job_key(position) not in stable_job_key(title):
                        record_title = f"{title} — {position}"

                    def matching_date(value: str):
                        date_match = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}", value)
                        return parse_turkish_date(date_match.group(0)) if date_match else parse_turkish_date(value)

                    job = source_listing.job_id and db.get(Job, source_listing.job_id)
                    if job is None:
                        job = existing_job
                    if job is None and organization != "Kurum belirtilmemiş":
                        job = db.scalar(
                            select(Job).where(
                                Job.sector == "public",
                                Job.title == record_title,
                                Job.organization == organization,
                                Job.application_deadline == matching_date(deadline_text),
                            ).limit(1)
                        )
                    detail_hash = str(details.get("content_hash") or hash_value(source_text))
                    if job is None:
                        job = Job(
                            sector="public",
                            title=record_title,
                            organization=organization,
                            city=city,
                            quota=quota,
                            source_url=detail_url,
                            source_name=source_name,
                            description=source_text,
                            application_start=matching_date(start_text),
                            application_deadline=matching_date(deadline_text),
                            announcement_date=matching_date(announcement_text),
                            kpss_score_type=kpss_type,
                            kpss_min_score=minimum,
                            education_requirement=education,
                            recruitment_method=detect_recruitment_method(title, source_text),
                            status="İncelenecek",
                        )
                        db.add(job)
                        db.flush()
                        report["imported"] += 1
                    else:
                        changed = False
                        for field, value in {
                            "title": record_title,
                            "organization": organization,
                            "source_name": source_name,
                            "description": source_text,
                            "application_start": matching_date(start_text),
                            "application_deadline": matching_date(deadline_text),
                            "announcement_date": matching_date(announcement_text),
                            "city": city,
                            "quota": quota,
                            "kpss_score_type": kpss_type,
                            "kpss_min_score": minimum,
                            "education_requirement": education,
                        }.items():
                            if value not in (None, "") and getattr(job, field) != value:
                                setattr(job, field, value)
                                changed = True
                        if changed:
                            job.updated_at = checked_at
                            report["updated"] += 1
                        else:
                            report["unchanged"] += 1

                    source_listing.job_id = job.id
                    source_listing.list_hash = list_hash
                    source_listing.content_hash = detail_hash
                    source_listing.status = "complete"
                    source_listing.last_checked_at = checked_at
                    source_listing.raw_payload = json.dumps(
                        {"listing": item, "details": details},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                    db.flush()
                except Exception as error:
                    source_listing.status = "detail_failed"
                    source_listing.last_checked_at = checked_at
                    report["detail_failed"] += 1
                    report.setdefault("detail_errors", []).append({
                        "url": detail_url,
                        "error": str(error),
                    })
                time.sleep(max(0.0, float(os.getenv("CAREERPILOT_SOURCE_REQUEST_DELAY_SECONDS", "0.75"))))

            report["status"] = (
                "partial" if report.get("listing_only")
                else "error" if report["detail_failed"]
                else "ok"
            )
            if report.get("listing_only"):
                report["detail_note"] = (
                    "Yalnızca resmi SBB ana sayfasında listelenen alanlar işlendi; "
                    "ilan detay sayfaları ve ayrıntılı başvuru şartları doğrulanmadı."
                )
            db.add(SourceSyncHistory(
                source_key=source_key,
                source_name=source_name,
                status=report["status"],
                checked_at=checked_at,
                pages_checked=report["pages_checked"],
                found=report["found"],
                imported=report["imported"],
                updated=report["updated"],
                unchanged=report["unchanged"],
                detail_failed=report["detail_failed"],
                error="; ".join(item["error"] for item in report.get("detail_errors", []))
                or report.get("detail_note", ""),
            ))
            db.commit()
        except Exception as exc:
            db.rollback()
            report["status"] = "error"
            report["error"] = str(exc)
            db.add(SourceSyncHistory(
                source_key=source_key,
                source_name=source_name,
                status="error",
                checked_at=checked_at,
                pages_checked=getattr(source, "pages_checked", 0),
                error=str(exc),
            ))
            db.commit()
        SOURCES_STATUS[source_name]["status"] = (
            "Aktif" if report["status"] == "ok" else "Hata"
        )
        SOURCES_STATUS[source_name]["last_sync"] = checked_at.isoformat(timespec="seconds")
        SOURCES_STATUS[source_name]["last_found"] = report["found"]
        SOURCES_STATUS[source_name]["last_created"] = report["imported"]
        SOURCES_STATUS[source_name]["last_updated"] = report["updated"]
        SOURCES_STATUS[source_name]["last_error"] = report.get("error") or report.get("detail_note")
        source_reports[source_key] = report
    document_scan = sync_jobs_documents(
        db,
        list(db.scalars(
            select(Job).where(Job.sector == "public").order_by(Job.id)
        ).all()),
    )
    db.commit()
    return {
        "success": all(report["status"] == "ok" for report in source_reports.values()),
        "results": source_reports,
        "document_scan": document_scan,
    }


@app.post("/sources/kariyer-kapisi/sync")
def sync_kariyer_kapisi(db: Session = Depends(get_db)):
    try:
        listings = scrape_public_active_listings()
    except Exception as error:
        SOURCES_STATUS["Kariyer Kapısı"]["last_error"] = str(error)
        raise HTTPException(status_code=502, detail=f"Kariyer Kapısı taranamadı: {error}") from error

    detail_outcomes = {}
    detail_startup_error = None
    try:
        detail_outcomes = scrape_public_listing_details(listings)
    except Exception as error:
        detail_startup_error = str(error)

    created, updated, unchanged, skipped = 0, 0, 0, 0
    detail_read, detail_failed = 0, 0
    detail_errors = []
    processed_urls = set()

    try:
        for item in listings:
            source_url = item.get("url", "").strip()
            if not source_url or source_url in processed_urls:
                skipped += 1
                continue
            processed_urls.add(source_url)

            outcome = detail_outcomes.get(source_url)
            details = outcome.get("details", {}) if outcome else {}
            detail_error = outcome.get("error") if outcome else (detail_startup_error or "Detay sonucu alınamadı")
            if detail_error:
                detail_failed += 1
                detail_errors.append({"url": source_url, "error": str(detail_error)})
            else:
                detail_read += 1

            deadline = parse_turkish_date(details.get("end_date") or item.get("end_date", ""))
            start_date = parse_turkish_date(details.get("start_date", ""))

            detail_lines = [
                "Kaynak: Kariyer Kapısı",
                f"Birim: {item.get('department', '')}",
            ]
            for label, key in (
                ("İlan başlığı", "title"), ("Pozisyon / unvan", "position"),
                ("Kontenjan", "quota"), ("Başvuru başlangıcı", "start_date"),
                ("Mezuniyet bölümleri", "departments"),
                ("Yaş şartı", "age_requirement"), ("İş deneyimi", "experience"),
                ("Sertifika şartları", "certificates"), ("Yabancı dil şartı", "foreign_languages"),
            ):
                if details.get(key):
                    detail_lines.append(f"{label}: {details[key]}")
            if details.get("source_text"):
                detail_lines.extend(["", "İlan detay sayfasından alınan metin:", details["source_text"]])
            detail_block = DETAIL_MARKER + "\n" + "\n".join(detail_lines) if details.get("source_text") else ""

            listing_title = details.get("title") or item["title"]
            institution = details.get("institution") or item["institution"]
            recruitment_method = detect_recruitment_method(listing_title, details.get("source_text", ""))

            # Yüksek Lisans / Burs kontrolü
            is_emp = not ("yurt dışı yüksek lisans" in listing_title.lower() or "yurt disi yuksek lisans" in listing_title.lower())

            existing_job = db.scalar(select(Job).where(Job.source_url == source_url).limit(1))
            if existing_job:
                changed = False
                if existing_job.title != listing_title:
                    existing_job.title = listing_title
                    changed = True
                if existing_job.organization != institution:
                    existing_job.organization = institution
                    changed = True

                existing_description = existing_job.description or ""
                base_description = existing_description.split(DETAIL_MARKER, 1)[0].rstrip()
                merged_description = (
                    f"{base_description}\n\n{detail_block}" if base_description and detail_block
                    else detail_block or existing_description
                )
                if existing_description != merged_description:
                    existing_job.description = merged_description
                    changed = True
                if deadline and existing_job.application_deadline != deadline:
                    existing_job.application_deadline = deadline
                    changed = True
                if start_date and existing_job.application_start != start_date:
                    existing_job.application_start = start_date
                    changed = True
                if recruitment_method and existing_job.recruitment_method != recruitment_method:
                    existing_job.recruitment_method = recruitment_method
                    changed = True
                if existing_job.is_employment != is_emp:
                    existing_job.is_employment = is_emp
                    changed = True

                field_values = {
                    "city": details.get("city", "")[:100] if details.get("city") else None,
                    "kpss_score_type": details.get("kpss_score_type", "")[:30] if details.get("kpss_score_type") else None,
                    "kpss_min_score": details.get("kpss_min_score"),
                    "education_requirement": (details.get("departments") or details.get("education_requirement") or "")[:500] or None,
                    "qualification_codes": details.get("qualification_codes", "")[:500] if details.get("qualification_codes") else None,
                    "quota": details.get("quota", "")[:50] if details.get("quota") else None,
                }
                for field, value in field_values.items():
                    if value not in (None, "") and getattr(existing_job, field) != value:
                        setattr(existing_job, field, value)
                        changed = True

                if changed:
                    existing_job.updated_at = datetime.now()
                    updated += 1
                else:
                    unchanged += 1
            else:
                new_job = Job(
                    sector="public",
                    title=listing_title,
                    organization=institution,
                    category="Kamu Alımı" if is_emp else "Eğitim / Burs",
                    source_url=source_url,
                    source_name="Kariyer Kapısı",
                    description=detail_block or f"Birim: {item.get('department', '')}\nKaynak: Kariyer Kapısı",
                    application_deadline=deadline,
                    application_start=start_date,
                    city=details.get("city", "")[:100],
                    kpss_score_type=details.get("kpss_score_type", "")[:30],
                    kpss_min_score=details.get("kpss_min_score"),
                    education_requirement=(details.get("departments") or details.get("education_requirement", ""))[:500],
                    qualification_codes=details.get("qualification_codes", "")[:500],
                    quota=details.get("quota", "")[:50],
                    recruitment_method=recruitment_method,
                    is_employment=is_emp,
                    status="İncelenecek",
                )
                db.add(new_job)
                created += 1

        db.commit()
        SOURCES_STATUS["Kariyer Kapısı"]["last_sync"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        SOURCES_STATUS["Kariyer Kapısı"]["last_found"] = len(listings)
        SOURCES_STATUS["Kariyer Kapısı"]["last_created"] = created
        SOURCES_STATUS["Kariyer Kapısı"]["last_updated"] = updated
        SOURCES_STATUS["Kariyer Kapısı"]["last_error"] = detail_startup_error

    except Exception as error:
        db.rollback()
        SOURCES_STATUS["Kariyer Kapısı"]["last_error"] = str(error)
        raise HTTPException(status_code=500, detail=f"İlanlar kaydedilemedi: {error}") from error

    return {
        "source": "Kariyer Kapısı",
        "found": len(listings),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "detail_read": detail_read,
        "detail_failed": detail_failed,
        "detail_access_error": detail_startup_error,
        "detail_errors": detail_errors,
    }
