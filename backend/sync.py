"""Kaynak senkronizasyonu: liste -> ilan kaydı -> ayrıntı/belge -> bildirim."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import logging
import re
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .document_sync import _save_document_positions, _scan_record, sync_jobs_documents
from .eligibility import (
    _extract_kpss_minimum,
    _extract_kpss_types,
    _sentences,
    detect_recruitment_method,
    normalize_text,
    reflow_text,
)
from .kariyerkapisi import _label_values
from .models import Job, JobDocument, JobDocumentScan, SourceListing, SourceSyncHistory
from .sources.registry import get_source_registry

logger = logging.getLogger(__name__)

TURKISH_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}
NON_EMPLOYMENT_PATTERN = re.compile(
    r"yuksek lisans egitimi|yurt disi yuksek lisans|(?<![a-z])burs(?:u|lar\w*)?(?![a-z])|staj programi|egitim programi|kariyer fuari"
)
_DATE = r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})"
_DATE_RANGE = re.compile(rf"{_DATE}\s*(?:tarihinden|tarihinde|gunu)?[^\d]{{0,60}}?{_DATE}")


def parse_turkish_date(text: str | date | None) -> date | None:
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    text = (text or "").strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    numeric = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", text)
    if numeric:
        return _safe_date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
    worded = re.search(r"\b(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})\b", text)
    if worded:
        month = TURKISH_MONTHS.get(normalize_text(worded.group(2)))
        if month:
            return _safe_date(int(worded.group(3)), month, int(worded.group(1)))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def application_window_from_text(text: str) -> tuple[date | None, date | None]:
    """İlan metnindeki "başvurular 10.11.2026 - 24.11.2026 tarihleri arasında" kalıbını okur."""
    flowed = normalize_text(reflow_text(text or ""))
    for sentence in _sentences(flowed):
        if "basvuru" not in sentence and "muracaat" not in sentence:
            continue
        match = _DATE_RANGE.search(sentence)
        if not match:
            continue
        start = _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        end = _safe_date(int(match.group(6)), int(match.group(5)), int(match.group(4)))
        if start and end and start <= end and (end - start).days <= 120:
            return start, end
    return None, None


def organization_key(value: str) -> str:
    """Farklı kaynaklardaki kurum adlarını karşılaştırmak için sadeleştirir."""
    text = re.sub(r"[^a-z0-9]+", " ", normalize_text(value))
    text = re.sub(r"\b(?:t c|tc|a s|as|tbmm|cumhurbaskanligi|genel mudurlugu|baskanligi|baskanligina|rektorlugu|mudurlugu|ili|ilcesi)\b", " ", text)
    text = re.sub(r"\bbelediye(?:si|sine)?\b", "belediye", text)
    words = text.split()
    if "belediye" in words:
        # "Edirne Keşan Belediyesi" ile "Keşan Belediye Başkanlığı" aynı kurumdur.
        index = words.index("belediye")
        if index >= 1:
            start = index - 2 if index >= 2 and words[index - 1] == "buyuksehir" else index - 1
            return " ".join(words[start:index + 1])
    return " ".join(words[:3])


def _hash(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _is_employment(title: str) -> bool:
    return NON_EMPLOYMENT_PATTERN.search(normalize_text(title)) is None


def _find_job(db: Session, source_name: str, source_listing: SourceListing | None, item: dict, user_url: str) -> Job | None:
    if source_listing is not None and source_listing.job_id:
        job = db.get(Job, source_listing.job_id)
        if job is not None:
            return job
    detail_url = str(item.get("detail_url") or "")
    for url in dict.fromkeys(filter(None, (detail_url, user_url if user_url != item.get("source_url") else ""))):
        job = db.scalar(select(Job).where(Job.source_url == url).limit(1))
        if job is not None:
            return job
    # Detay bağlantısı kalıcı olmayan kaynaklarda (SBB) kurum + başlık ile eşleştir.
    target = normalize_text(f"{item.get('institution', '')} {item.get('title', '')}")
    target = re.sub(r"[^a-z0-9]+", " ", target).strip()
    if not target:
        return None
    for candidate in db.scalars(select(Job).where(Job.sector == "public", Job.source_name == source_name)).all():
        key = re.sub(r"[^a-z0-9]+", " ", normalize_text(f"{candidate.organization} {candidate.title}")).strip()
        if key == target and candidate.application_deadline == parse_turkish_date(item.get("application_end_date")):
            return candidate
    return None


def _set(job: Job, field: str, value, *, overwrite: bool = True) -> bool:
    if value in (None, ""):
        return False
    current = getattr(job, field)
    if current == value or (not overwrite and current not in (None, "")):
        return False
    setattr(job, field, value)
    return True


def _apply_listing(job: Job, item: dict, source_name: str, user_url: str) -> bool:
    changed = False
    changed |= _set(job, "title", str(item.get("title") or "")[:250])
    changed |= _set(job, "organization", str(item.get("institution") or "")[:250])
    changed |= _set(job, "source_name", source_name)
    changed |= _set(job, "source_url", user_url[:1000])
    changed |= _set(job, "city", str(item.get("city") or "")[:100], overwrite=False)
    changed |= _set(job, "quota", str(item.get("quota") or "")[:50], overwrite=False)
    changed |= _set(job, "employment_type", str(item.get("employment_type") or "")[:100], overwrite=False)
    changed |= _set(job, "application_start", parse_turkish_date(item.get("application_start_date")))
    changed |= _set(job, "application_deadline", parse_turkish_date(item.get("application_end_date")))
    changed |= _set(job, "announcement_date", parse_turkish_date(item.get("announcement_date")))
    return changed


def _apply_detail(job: Job, item: dict, details: dict) -> bool:
    text = str(details.get("source_text") or "").strip()
    labels = _label_values(text)
    changed = _set(job, "description", text)
    sentences = [(sentence, normalize_text(sentence)) for sentence in _sentences(reflow_text(text))]
    sentences.append((job.title, normalize_text(job.title)))

    kpss_type = str(details.get("kpss_score_type") or "") or "/".join(_extract_kpss_types({}, sentences))
    changed |= _set(job, "kpss_score_type", kpss_type[:30])
    minimum = details.get("kpss_min_score")
    if minimum is None:
        minimum = _extract_kpss_minimum({}, sentences)
    changed |= _set(job, "kpss_min_score", minimum)

    start_text = details.get("start_date") or labels.get("start_date")
    end_text = details.get("end_date") or labels.get("end_date")
    text_start, text_end = application_window_from_text(text)
    changed |= _set(job, "application_start", parse_turkish_date(start_text) or text_start, overwrite=False)
    changed |= _set(job, "application_deadline", parse_turkish_date(end_text) or text_end, overwrite=False)
    changed |= _set(job, "announcement_date", parse_turkish_date(details.get("announcement_date")), overwrite=False)

    changed |= _set(job, "organization", str(details.get("institution") or labels.get("institution") or "")[:250], overwrite=False)
    changed |= _set(job, "city", str(details.get("city") or labels.get("city") or "")[:100], overwrite=False)
    changed |= _set(job, "quota", str(details.get("quota") or labels.get("quota") or "")[:50], overwrite=False)
    education = str(details.get("departments") or details.get("education_requirement") or "")
    changed |= _set(job, "education_requirement", education[:500])
    changed |= _set(job, "qualification_codes", str(details.get("qualification_codes") or "")[:500])
    method = detect_recruitment_method(job.title, text)
    changed |= _set(job, "recruitment_method", method)
    if not job.employment_type:
        normalized = normalize_text(f"{job.title} {text[:3000]}")
        employment = (
            "Sözleşmeli" if "sozlesmeli" in normalized
            else "İşçi" if re.search(r"\bisci\b", normalized)
            else "Memur" if re.search(r"\bmemur|zabita|itfaiye eri|uzman yardimci|mufettis yardimci", normalized)
            else ""
        )
        changed |= _set(job, "employment_type", employment)
    return changed


def _store_document(db: Session, job: Job, document: dict, checked_at: datetime) -> int:
    url = str(document.get("url") or job.source_url or "")[:1200]
    parsed = document.get("parsed") or {}
    record = db.scalar(select(JobDocument).where(JobDocument.job_id == job.id, JobDocument.document_url == url))
    if record is None:
        record = JobDocument(job_id=job.id, document_url=url)
        db.add(record)
    record.title = str(document.get("title") or "Resmî ilan metni")[:500]
    record.content_type = str(document.get("content_type") or "")[:200]
    record.content_hash = record.parsed_content_hash = str(document.get("body_hash") or "")
    record.extracted_text = parsed.get("text") or ""
    record.shared_requirements = parsed.get("shared_requirements") or ""
    record.status = "partially_read" if parsed.get("partially_read") else "read"
    record.error = "Belgenin metninde çözümlenemeyen karakterler var." if parsed.get("partially_read") else ""
    record.checked_at = checked_at
    db.flush()
    positions = parsed.get("positions") or []
    _save_document_positions(db, record, positions)
    scan = _scan_record(db, job.id)
    scan.status = "complete"
    scan.attachments_found = 1
    scan.error = ""
    scan.checked_at = checked_at
    return len(positions)


def _store_unread_attachment(db: Session, job: Job, attachment: dict, checked_at: datetime) -> None:
    """Okunamayan resmî eki, kullanıcının kendisi açabilmesi için bağlantı olarak kaydeder."""
    url = str(attachment.get("url") or "")[:1200]
    if not url:
        return
    record = db.scalar(select(JobDocument).where(JobDocument.job_id == job.id, JobDocument.document_url == url))
    if record is None:
        record = JobDocument(job_id=job.id, document_url=url)
        db.add(record)
    if record.status != "read":
        record.title = str(attachment.get("title") or "Ek belge")[:500]
        record.status = "unavailable"
        record.error = str(attachment.get("error") or "Belge otomatik okunamadı.")
        record.checked_at = checked_at
    scan = _scan_record(db, job.id)
    if scan.status != "complete":
        scan.status = "partial"
        scan.attachments_found = max(scan.attachments_found or 0, 1)
        scan.error = "Ek belge otomatik okunamadı; bağlantıdan açıp kontrol edin."
        scan.checked_at = checked_at


def _role_words(title: str) -> set[str]:
    normalized = normalize_text(title)
    roles = {word for word in ("zabita", "itfaiye", "sozlesmeli", "isci") if word in normalized}
    if not roles and "memur" in normalized:
        roles.add("memur")
    return roles


def _mark_cancelled(db: Session, source_name: str, item: dict) -> int:
    """İptal duyurusu geldiğinde aynı kurumun aynı türdeki açık ilanlarını (tüm kaynaklarda) işaretler."""
    key = organization_key(str(item.get("institution") or ""))
    if not key:
        return 0
    roles = _role_words(item.get("title") or "")
    count = 0
    for job in db.scalars(select(Job).where(Job.sector == "public", Job.status != "İptal edildi")).all():
        if organization_key(job.organization) != key:
            continue
        if roles and roles != _role_words(job.title):
            continue
        announced = parse_turkish_date(item.get("announcement_date"))
        if announced and job.announcement_date and job.announcement_date > announced:
            continue  # iptalden sonra yayımlanan yeni ilan
        job.status = "İptal edildi"
        job.updated_at = datetime.now()
        count += 1
    return count


def sync_source(db: Session, source_key: str, source, *, delay: float | None = None, on_progress=None) -> dict:
    """Tek kaynağı tarar; hata durumunda mevcut kayıtlara dokunmaz."""
    delay = config.source_request_delay() if delay is None else delay
    source_name = source.source_name
    checked_at = datetime.now()
    report = {
        "status": "ok", "source": source_name, "pages_checked": 0, "found": 0, "imported": 0,
        "updated": 0, "unchanged": 0, "detail_failed": 0, "cancelled": 0, "error": None,
        "detail_errors": [], "touched_job_ids": [],
    }
    try:
        listings = source.fetch_listings()
        report["pages_checked"] = getattr(source, "pages_checked", 0)
        report["found"] = len(listings)

        cancellations: list[dict] = []
        for index, item in enumerate(listings):
            if on_progress:
                on_progress(source_name, index + 1, len(listings))
            detail_url = str(item.get("detail_url") or "").strip()
            external = str(item.get("external_id") or detail_url).strip()
            if not detail_url or not external or not str(item.get("title") or "").strip():
                report["detail_failed"] += 1
                continue
            if item.get("is_cancellation"):
                cancellations.append(item)
                continue

            user_url = str(item.get("user_url") or detail_url)
            list_hash = str(item.get("content_hash") or _hash(item))
            listing = db.scalar(select(SourceListing).where(
                SourceListing.source_key == source_key, SourceListing.external_id == external,
            ))
            job = _find_job(db, source_name, listing, item, user_url)
            created = job is None
            if created:
                job = Job(
                    sector="public", category="Kamu Alımı", status="İncelenecek", source_name=source_name,
                    title=str(item.get("title"))[:250], organization=str(item.get("institution") or "")[:250],
                    source_url=user_url[:1000], description=str(item.get("description_html") or ""),
                    recruitment_method=str(item.get("recruitment_method") or ""),
                    is_employment=_is_employment(str(item.get("title"))),
                    created_at=checked_at,
                )
                db.add(job)
            changed = _apply_listing(job, item, source_name, user_url)
            db.flush()
            if listing is None:
                listing = SourceListing(
                    source_key=source_key, external_id=external[:300], official_url=detail_url[:1200],
                    status="pending_detail",
                )
                db.add(listing)
            listing.job_id = job.id
            listing.official_url = detail_url[:1200]
            listing.last_checked_at = checked_at

            needs_detail = created or listing.status != "complete" or listing.list_hash != list_hash
            if needs_detail:
                try:
                    details = source.fetch_detail(detail_url)
                    if len(str(details.get("source_text") or "").strip()) < 80:
                        raise ValueError("Ayrıştırılabilir ilan metni bulunamadı.")
                    changed |= _apply_detail(job, item, details)
                    db.flush()
                    if details.get("document"):
                        _store_document(db, job, details["document"], checked_at)
                    for attachment in details.get("unread_attachments") or []:
                        _store_unread_attachment(db, job, attachment, checked_at)
                    listing.content_hash = str(details.get("content_hash") or "")[:64]
                    listing.status = "complete"
                    listing.raw_payload = json.dumps(
                        {"listing": item, "detail_keys": sorted(details)}, ensure_ascii=False, sort_keys=True, default=str,
                    )[:20000]
                except Exception as error:  # tek ilanın hatası taramayı durdurmaz
                    listing.status = "detail_failed"
                    report["detail_failed"] += 1
                    report["detail_errors"].append({"url": user_url, "title": job.title, "error": str(error)[:300]})
                    logger.warning("Detail fetch failed for %s: %s", detail_url, error)
                if delay:
                    time.sleep(delay)
            listing.list_hash = list_hash

            if created:
                report["imported"] += 1
                report["touched_job_ids"].append(job.id)
            elif changed:
                job.updated_at = checked_at
                report["updated"] += 1
                report["touched_job_ids"].append(job.id)
            else:
                report["unchanged"] += 1
            db.commit()

        # İptal duyuruları, ilgili ilanlar kaydedildikten sonra uygulanır.
        for item in cancellations:
            report["cancelled"] += _mark_cancelled(db, source_name, item)
        db.commit()
        report["status"] = "partial" if report["detail_failed"] else "ok"
    except Exception as error:
        db.rollback()
        report["status"] = "error"
        report["error"] = str(error)[:500]
        logger.warning("Source %s failed: %s", source_key, error)

    summary_error = report["error"] or "; ".join(
        f"{item['title'][:60]}: {item['error']}" for item in report["detail_errors"][:5]
    )
    db.add(SourceSyncHistory(
        source_key=source_key, source_name=source_name, status=report["status"], checked_at=checked_at,
        pages_checked=report["pages_checked"], found=report["found"], imported=report["imported"],
        updated=report["updated"], unchanged=report["unchanged"], detail_failed=report["detail_failed"],
        error=summary_error or "",
    ))
    db.commit()
    return report


def run_sync(db: Session, *, registry: dict | None = None, on_progress=None, scan_documents: bool = True) -> dict:
    """Bütün kaynakları tarar, ek belgeleri okur ve yeni eşleşmeler için bildirim üretir."""
    from .notifications import process_notifications

    registry = registry if registry is not None else get_source_registry()
    results = {}
    for source_key, source in registry.items():
        if on_progress:
            on_progress(source.source_name, 0, 0)
        results[source_key] = sync_source(db, source_key, source, on_progress=on_progress)

    document_scan = None
    if scan_documents:
        # Detayı HTML sayfası olan Kariyer Kapısı ilanlarının ek belgelerini oku.
        document_sources = {"Kariyer Kapısı"}
        scanned = {
            scan.job_id for scan in db.scalars(select(JobDocumentScan).where(JobDocumentScan.status == "complete")).all()
        }
        touched = {job_id for report in results.values() for job_id in report["touched_job_ids"]}
        today = date.today()
        jobs = [
            job for job in db.scalars(select(Job).where(Job.sector == "public").order_by(Job.id)).all()
            if job.source_name in document_sources
            and (job.id in touched or job.id not in scanned)
            and (job.application_deadline is None or job.application_deadline >= today)
        ]
        if jobs:
            if on_progress:
                on_progress("Ek belgeler", 0, len(jobs))
            try:
                document_scan = sync_jobs_documents(db, jobs)
                db.commit()
            except Exception as error:
                db.rollback()
                document_scan = {"errors": 1, "details": [{"error": str(error)[:300]}]}

    from .matching import invalidate_cache

    invalidate_cache()
    notifications = process_notifications(db)
    for report in results.values():
        report.pop("touched_job_ids", None)
    return {
        "success": all(report["status"] == "ok" for report in results.values()),
        "results": results,
        "document_scan": document_scan,
        "notifications": notifications,
    }


def cleanup_legacy_rows(db: Session) -> dict:
    """Eski sürümlerden kalan ilan olmayan kayıtları ve aynı kaynaktaki kopyaları temizler."""
    from .models import DocumentPosition, Notification
    from .sources.yerel_yonetimler import parse_announcement_title

    def remove(job: Job, keep: Job | None = None) -> None:
        for listing in db.scalars(select(SourceListing).where(SourceListing.job_id == job.id)).all():
            if keep is not None:
                listing.job_id = keep.id
            else:
                db.delete(listing)
        for document in db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all():
            for row in db.scalars(select(DocumentPosition).where(DocumentPosition.document_id == document.id)).all():
                db.delete(row)
            db.delete(document)
        for scan in db.scalars(select(JobDocumentScan).where(JobDocumentScan.job_id == job.id)).all():
            db.delete(scan)
        for notification in db.scalars(select(Notification).where(Notification.job_id == job.id)).all():
            db.delete(notification)
        if keep is not None and job.tracking and not keep.tracking:
            keep.tracking = job.tracking
        db.delete(job)

    removed = merged = 0
    jobs = list(db.scalars(select(Job).where(Job.sector == "public")).all())
    survivors = []
    for job in jobs:
        parsed = parse_announcement_title(job.title)
        if job.source_name == "Yerel Yönetimler Genel Müdürlüğü" and (not parsed["is_recruitment"] or parsed["is_cancellation"]):
            remove(job)
            removed += 1
        else:
            survivors.append(job)
    groups: dict[tuple, list[Job]] = {}
    for job in survivors:
        if job.source_name in ("Manuel Giriş", "Toplu Yükleme"):
            continue
        if job.is_employment != _is_employment(job.title):
            job.is_employment = _is_employment(job.title)
            db.flush()
        title_key = re.sub(r"[^a-z0-9]+", " ", normalize_text(job.title)).strip()
        groups.setdefault((job.source_name, organization_key(job.organization), title_key, job.application_deadline), []).append(job)
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda job: (len(job.description or ""), -job.id))
        for job in members:
            if job.id != keep.id:
                remove(job, keep)
                merged += 1
    db.commit()
    return {"removed": removed, "merged": merged}


class SyncManager:
    """Arka planda tek seferde bir tarama çalıştırır ve durumunu raporlar."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None
        self._stop = threading.Event()
        self.state: dict = {
            "running": False, "trigger": None, "started_at": None, "finished_at": None,
            "progress": None, "report": None, "error": None,
        }

    def status(self) -> dict:
        return dict(self.state)

    def start(self, trigger: str = "manual") -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self.state.update(
                running=True, trigger=trigger, started_at=datetime.now().isoformat(timespec="seconds"),
                finished_at=None, progress={"source": "Hazırlanıyor", "current": 0, "total": 0}, error=None,
            )
        self._thread = threading.Thread(target=self._run, name="careerpilot-sync", daemon=True)
        self._thread.start()
        return True

    def _progress(self, source: str, current: int, total: int) -> None:
        self.state["progress"] = {"source": source, "current": current, "total": total}

    def _run(self) -> None:
        from .database import SessionLocal

        try:
            with SessionLocal() as db:
                self.state["report"] = run_sync(db, on_progress=self._progress)
        except Exception as error:  # pragma: no cover - beklenmeyen hata durumunu kullanıcıya göster
            logger.exception("Sync run failed")
            self.state["error"] = str(error)[:500]
        finally:
            self.state.update(
                running=False, progress=None, finished_at=datetime.now().isoformat(timespec="seconds"),
            )

    # ---- otomatik tarama ----
    def start_scheduler(self) -> None:
        interval = config.sync_interval_hours()
        if interval <= 0 or config.is_read_only() or self._scheduler is not None:
            return
        self._stop.clear()
        self._scheduler = threading.Thread(target=self._schedule_loop, args=(interval,), name="careerpilot-scheduler", daemon=True)
        self._scheduler.start()

    def stop_scheduler(self) -> None:
        self._stop.set()
        self._scheduler = None

    def _schedule_loop(self, interval_hours: float) -> None:
        from .database import SessionLocal

        # Sunucu açılışında hemen değil, kısa bir beklemeden sonra kontrol et.
        if self._stop.wait(45):
            return
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    last = db.scalar(select(SourceSyncHistory.checked_at).order_by(SourceSyncHistory.checked_at.desc()).limit(1))
                due = last is None or datetime.now() - last >= timedelta(hours=interval_hours)
                if due:
                    self.start("auto")
            except Exception:  # pragma: no cover
                logger.exception("Scheduler check failed")
            if self._stop.wait(600):
                return


sync_manager = SyncManager()
