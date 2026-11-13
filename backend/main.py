import os
from datetime import date, datetime
from datetime import timedelta
import re

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import CandidateProfile, Job
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
)
from .kariyerkapisi import (
    DETAIL_MARKER,
    scrape_public_active_listings,
    scrape_public_listing_details,
)
from .migrate import migrate as run_migrations
from .sources.registry import get_source_registry


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


@app.middleware("http")
async def restrict_demo_api(request, call_next):
    if DEMO_MODE:
        path = request.url.path.rstrip("/") or "/"
        public_get_paths = {"/health", "/sources", "/sources/status", "/public/listings", "/public/summary"}
        is_public_source_list = re.fullmatch(r"/sources/[^/]+/listings", path) is not None
        if request.method != "GET" or (path not in public_get_paths and not is_public_source_list):
            return JSONResponse(status_code=404, content={"detail": "Bu uç nokta herkese açık demo modunda kullanılamaz."})
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
    if start_date and start_date > today:
        return "Başvuru Başlamadı"
    if end_date and end_date < today:
        return "Başvuru Sona Erdi"
    if start_date and end_date:
        return "Başvuru Açık"
    return "Tarih belirtilmemiş"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "CareerPilot TR API",
        "version": "0.4.0",
        "demo_mode": DEMO_MODE,
    }


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

    # 1. TÜRKŞEKER Pozisyonları
    if "şeker fabrikaları" in org_norm or "turkseker" in title_norm or "şeker fabrikaları" in title_norm:
        return [
            {
                "sub_id": f"{job.id}-ce",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Bilgisayar Mühendisi",
                "position": "Bilgisayar Mühendisi",
                "quota": "2",
                "city": "Ankara",
                "kpss_score_type": "P3",
                "kpss_min_score": 70.0,
                "education_requirement": "Fakültelerin dört yıllık Bilgisayar Mühendisliği bölümlerinden mezun olmak",
                "qualification_codes": "",
                "description": job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "Kurum giriş sınavı",
            },
            {
                "sub_id": f"{job.id}-ee",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Elektrik-Elektronik Mühendisi",
                "position": "Elektrik-Elektronik Mühendisi",
                "quota": "Belirtilmemiş",
                "city": "Taşra Teşkilatı",
                "kpss_score_type": "P3",
                "kpss_min_score": 70.0,
                "education_requirement": "Elektrik-Elektronik Mühendisliği mezunu olmak",
                "qualification_codes": "",
                "description": "Elektrik-Elektronik Mühendisliği bölümünden mezun olmak.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "Kurum giriş sınavı",
            },
            {
                "sub_id": f"{job.id}-makine",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Makine Mühendisi",
                "position": "Makine Mühendisi",
                "quota": "Belirtilmemiş",
                "city": "Taşra Teşkilatı",
                "kpss_score_type": "P3",
                "kpss_min_score": 70.0,
                "education_requirement": "Makine Mühendisliği mezunu olmak",
                "qualification_codes": "",
                "description": "Makine Mühendisliği bölümünden mezun olmak.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "Kurum giriş sınavı",
            },
            {
                "sub_id": f"{job.id}-diger",
                "parent_id": job.id,
                "organization": job.organization,
                "title": f"{job.title} — Diğer Branşlar (İnşaat, Ziraat, Kimya, Tekniker)",
                "position": "İnşaat/Ziraat/Kimya Mühendisi ve Tekniker",
                "quota": "Belirtilmemiş",
                "city": "Taşra Teşkilatı",
                "kpss_score_type": "P3",
                "kpss_min_score": 70.0,
                "education_requirement": "İnşaat, Ziraat, Kimya Mühendisliği veya Teknikerlik bölümlerinden mezun olmak",
                "qualification_codes": "",
                "description": "İnşaat, Ziraat veya Kimya Mühendisliği mezunu olmak.\n" + job.description,
                "source_url": job.source_url,
                "source_name": job.source_name or "Kariyer Kapısı",
                "application_start": job.application_start,
                "application_deadline": job.application_deadline,
                "recruitment_method": "Kurum giriş sınavı",
            },
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

        # İstihdam ilanını pozisyonlarına ayrıştır
        sub_positions = decompose_job_positions(job)
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
                "application_start": pos["application_start"].isoformat() if pos["application_start"] else None,
                "application_deadline": pos["application_deadline"].isoformat() if pos["application_deadline"] else None,
                "application_status": app_status,
                "is_expired": (app_status == "Başvuru Sona Erdi"),
                "recruitment_method": pos["recruitment_method"],
                "education_requirement": match["education"]["requirement"] or pos["education_requirement"],
                "qualification_codes": pos["qualification_codes"] or ", ".join(match["qualification_codes"]),
                "kpss_score_type": pos["kpss_score_type"] or "/".join(match["kpss"]["score_types"]),
                "kpss_min_score": pos["kpss_min_score"] if pos["kpss_min_score"] is not None else match["kpss"]["minimum_score"],
                "description": pos["description"],
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


# ============================================================
# KAYNAK LİSTESİ VE SENKRONİZASYON DURUMU
# ============================================================

@app.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    sources_data = []
    for source_key, info in SOURCES_STATUS.items():
        job_count = db.scalar(
            select(func.count(Job.id)).where(Job.source_name == source_key)
        ) or 0
        sources_data.append({
            "name": info["name"],
            "url": info["url"],
            "description": info["description"],
            "status": info["status"],
            "job_count": job_count,
            "last_sync": info["last_sync"],
            "last_found": info["last_found"],
            "last_created": info["last_created"],
            "last_updated": info["last_updated"],
            "last_error": info["last_error"],
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
        Job.application_deadline,
        Job.recruitment_method,
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
            "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
            "application_status": application_status,
            "recruitment_method": job.recruitment_method or None,
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
    registry = get_source_registry()
    source_reports = {}
    for name, source in registry.items():
        source_name = source.source_name
        now = datetime.now()
        try:
            listings = source.fetch_listings() or []
            records = 0
            for item in listings:
                detail_url = item.get("detail_url") or item.get("source_url")
                if not detail_url:
                    continue
                existing = db.scalar(select(Job).where(Job.source_url == detail_url).limit(1))
                if existing:
                    continue
                db.add(Job(
                    sector="public",
                    title=item.get("title") or "Kamu İlanı",
                    organization=item.get("institution") or item.get("source_name") or source_name,
                    city=item.get("city") or "",
                    source_url=detail_url,
                    source_name=source_name,
                    description=item.get("description_html") or item.get("title") or "",
                    application_deadline=parse_turkish_date(item.get("application_end_date") or item.get("announcement_date") or "") if item.get("application_end_date") or item.get("announcement_date") else None,
                    recruitment_method="Kaynak otomasyonu",
                    status="İncelenecek",
                ))
                records += 1
            db.commit()
            SOURCES_STATUS[source_name]["status"] = "Aktif"
            SOURCES_STATUS[source_name]["last_sync"] = now.isoformat(timespec="seconds")
            SOURCES_STATUS[source_name]["last_found"] = records
            source_reports[name] = {"status": "ok", "imported": records, "source": source_name}
        except Exception as exc:
            SOURCES_STATUS[source_name]["status"] = "Hata"
            SOURCES_STATUS[source_name]["last_error"] = str(exc)
            source_reports[name] = {"status": "error", "error": str(exc), "source": source_name}
    return {"success": True, "results": source_reports}


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
