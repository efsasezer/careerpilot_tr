"""Kaynak senkronizasyonu: liste -> ilan kaydı -> ayrıntı/belge -> bildirim."""

from __future__ import annotations

from . import clock
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
from .events import refresh_all_events, sync_job_events
from .kariyerkapisi import _label_values
from .models import Job, JobDocument, JobDocumentScan, SourceListing, SourceSyncHistory, UserVerification
from .sources.base import classify_error
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
_DATE_RANGE = re.compile(
    rf"{_DATE}\s*(?:[-–—]\s*|\s+(?:ile|ve)\s+|\s+tarihinden(?:\s+baslayarak)?\s*){_DATE}"
)
_APPLICATION_DEADLINE = re.compile(
    r"\b(?:son\s+(?:basvuru|muracaat)\s*(?:tarihi|gunu)?|"
    r"basvuru(?:nun)?\s+(?:son\s+gunu|bitis(?:\s+tarihi)?)|"
    r"basvuru\s+suresinin\s+son\s+gunu|basvurularin\s+son\s+gunu)\b"
)


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
    sentences = _sentences(flowed)
    for index, sentence in enumerate(sentences):
        match = _DATE_RANGE.search(sentence)
        if not match:
            continue
        context = " ".join(sentences[max(0, index - 2):index + 1])
        if not any(word in context for word in ("basvuru", "muracaat", "tercih")):
            continue
        start = _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        end = _safe_date(int(match.group(6)), int(match.group(5)), int(match.group(4)))
        if start and end and start <= end and (end - start).days <= 120:
            return start, end
    return None, None


def application_deadline_from_text(text: str) -> date | None:
    """Return a date only when nearby wording identifies it as an application deadline."""
    for sentence in _sentences(reflow_text(text or "")):
        normalized = normalize_text(sentence)
        labels = list(_APPLICATION_DEADLINE.finditer(normalized))
        if not labels:
            continue
        dates = list(re.finditer(_DATE, sentence))
        for label in labels:
            nearby = [
                match for match in dates
                if (
                    0 <= match.start() - label.end() <= 80
                    or 0 <= label.start() - match.end() <= 40
                )
            ]
            if nearby:
                return parse_turkish_date(nearby[0].group())
    return None


_MONTH_NAMES = "ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik"
_WORDED_POINTS = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({_MONTH_NAMES})\s+(20\d{{2}})"            # 1-7 Aralık 2026
    rf"|(?<!\d)(\d{{1,2}})\s+({_MONTH_NAMES})\s*[-–]\s*(\d{{1,2}})\s+({_MONTH_NAMES})\s+(20\d{{2}})"  # 16 Kasım - 4 Aralık 2026
    rf"|(?<!\d)(\d{{1,2}})\s+({_MONTH_NAMES})\s+(20\d{{2}})"                                   # 3 Kasım 2026
    rf"|(?<!\d)(\d{{1,2}})\s*[./]\s*(\d{{1,2}})\s*[./]\s*(20\d{{2}})(?!\d)"                    # 03.11.2026
)
_NOT_APPLICATION = ("ucret", "itiraz", "sonuc", "dogmus", "dogumlu", "mezun", "sayili", "resmi gazete", "yasini")
_WINDOW_CUE = ("arasinda", "baslayip", "baslayacak", "baslar", "sona er", "bitecek", "kadar", " - ", "–", "ile ")
_DEADLINE_CUE = ("son basvuru", "sona er", "kadar", "bitis", "son gun", "son muracaat")


def _date_points(normalized: str) -> list[date]:
    """Cümledeki tarih noktaları; "1-7 Aralık 2026" gibi aralıklar iki noktaya açılır."""
    months = _MONTH_NAMES.split("|")
    points: list[date | None] = []
    for match in _WORDED_POINTS.finditer(normalized):
        g = match.groups()
        if g[0]:
            month, year = months.index(g[2]) + 1, int(g[3])
            points += [_safe_date(year, month, int(g[0])), _safe_date(year, month, int(g[1]))]
        elif g[4]:
            year = int(g[8])
            first_month, second_month = months.index(g[5]) + 1, months.index(g[7]) + 1
            points += [_safe_date(year - 1 if first_month > second_month else year, first_month, int(g[4])),
                       _safe_date(year, second_month, int(g[6]))]
        elif g[9]:
            points.append(_safe_date(int(g[11]), months.index(g[10]) + 1, int(g[9])))
        else:
            points.append(_safe_date(int(g[14]), int(g[13]), int(g[12])))
    return [point for point in points if point]


def worded_application_window(text: str) -> tuple[date | None, date | None]:
    """Ay adıyla ya da "başlayıp ... sona erecektir" biçiminde yazılmış başvuru dönemini okur.

    Yalnızca başvurudan söz eden, ücret/itiraz/sonuç içermeyen cümleler kullanılır. Cümlede tam iki
    tarih ve bir aralık ifadesi varsa (başlangıç, bitiş); tek tarih ve "son başvuru / kadar" ifadesi
    varsa yalnızca bitiş döner. Birden çok başvuru dönemi sayan cümlelerden tarih seçilmez.
    """
    for sentence in _sentences(reflow_text(text or "")):
        normalized = normalize_text(sentence)
        if len(normalized) > 500 or not any(word in normalized for word in ("basvuru", "muracaat")):
            continue
        if any(word in normalized for word in _NOT_APPLICATION):
            continue
        points = _date_points(normalized)
        if len(points) == 2 and any(cue in normalized for cue in _WINDOW_CUE):
            start, end = points
            if start <= end and (end - start).days <= 120:
                return start, end
        elif len(points) == 1 and any(cue in normalized for cue in _DEADLINE_CUE):
            return None, points[0]
    return None, None


def organization_key(value: str) -> str:
    """Farklı kaynaklardaki kurum adlarını karşılaştırmak için sadeleştirir."""
    text = re.sub(r"\([^)]*\)", " ", normalize_text(value))  # "(YÖK)" gibi kısaltmalar
    text = re.sub(r"[^a-z0-9]+", " ", text)
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
        if job is not None and not job.archived_reason:
            return job
    detail_url = str(item.get("detail_url") or "")
    for url in dict.fromkeys(filter(None, (detail_url, user_url if user_url != item.get("source_url") else ""))):
        job = db.scalar(select(Job).where(Job.source_url == url, Job.archived_reason == "").limit(1))
        if job is not None:
            return job
    # Detay bağlantısı kalıcı olmayan kaynaklarda (SBB) kurum + başlık ile eşleştir.
    target = normalize_text(f"{item.get('institution', '')} {item.get('title', '')}")
    target = re.sub(r"[^a-z0-9]+", " ", target).strip()
    if not target:
        return None
    for candidate in db.scalars(select(Job).where(
        Job.sector == "public", Job.source_name == source_name, Job.archived_reason == "",
    )).all():
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
    text_deadline = application_deadline_from_text(text)
    if text_end is None and text_deadline is None:
        worded_start, worded_end = worded_application_window(text)
        text_start, text_end = text_start or worded_start, worded_end
    changed |= _set(job, "application_start", parse_turkish_date(start_text) or text_start, overwrite=False)
    changed |= _set(
        job, "application_deadline",
        parse_turkish_date(end_text) or text_end or text_deadline,
        overwrite=False,
    )
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
    record.ocr_confidence = parsed.get("ocr_confidence")
    if record.ocr_confidence is not None:
        record.status = "ocr"
        record.error = f"Taranmış PDF, OCR ile okundu (güven %{round(record.ocr_confidence * 100)}); kontrol edin."
    else:
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


def _retire_unrelated_documents(db: Session, job: Job, details: dict) -> None:
    """Kaynak bu ilanın eklerinin tam listesini verdiyse, listede olmayan eski belge kayıtlarını devre dışı bırakır.

    Eski sürümler sayfanın menüsündeki ilgisiz bağlantıları da ek belge saymıştı. Kayıt silinmez;
    durumu "obsolete" olur ve metni uygunluk ile tarih çıkarımında kullanılmaz.
    """
    current = details.get("attachment_urls")
    if current is None:
        return
    keep = {str(url) for url in current}
    for record in db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all():
        if record.document_url not in keep and record.status != "obsolete":
            record.status = "obsolete"


def _role_words(title: str) -> set[str]:
    normalized = normalize_text(title)
    roles = {word for word in ("zabita", "itfaiye", "sozlesmeli", "isci") if word in normalized}
    if not roles and "memur" in normalized:
        roles.add("memur")
    return roles


def _mark_cancelled(db: Session, source_name: str, item: dict) -> int:
    """İptal duyurusunu ilgili ilana uygular.

    Yalnızca duyuru hangi alımı iptal ettiğini açıkça söylüyorsa (ör. "memur alımı iptal ilanı")
    ve kurumun o türde her kaynakta tek ilanı varsa ilan "İptal edildi" olur. Aksi hâlde hiçbir
    ilan iptal sayılmaz; kurumun açık ilanlarına "iptal duyurusu var, doğrulayın" notu düşülür.
    """
    key = organization_key(str(item.get("institution") or ""))
    if not key:
        return 0
    title = str(item.get("title") or "")
    normalized = normalize_text(title)
    roles = _role_words(title)
    partial = bool(re.search(r"\d", normalized)) or "kadro iptal" in normalized or "kismi" in normalized
    announced = parse_turkish_date(item.get("announcement_date"))
    candidates = [
        job for job in db.scalars(select(Job).where(
            Job.sector == "public", Job.status != "İptal edildi", Job.archived_reason == "",
        )).all()
        if organization_key(job.organization) == key
        and "iptal ilan" not in normalize_text(job.title)
        and not (announced and job.announcement_date and job.announcement_date > announced)
    ]
    matching = [job for job in candidates if roles and roles == _role_words(job.title)]
    per_source: dict[str, int] = {}
    for job in matching:
        per_source[job.source_name] = per_source.get(job.source_name, 0) + 1
    if matching and not partial and all(count == 1 for count in per_source.values()):
        for job in matching:
            job.status = "İptal edildi"
            job.cancellation_notice = f"{source_name}: {title}"[:400]
            job.updated_at = clock.now()
        return len(matching)
    for job in candidates:
        notice = f"{source_name}: {title}"[:400]
        if job.cancellation_notice != notice:
            job.cancellation_notice = notice
            job.updated_at = clock.now()
    return 0


def sync_source(db: Session, source_key: str, source, *, delay: float | None = None, on_progress=None) -> dict:
    """Tek kaynağı tarar; hata durumunda mevcut kayıtlara dokunmaz."""
    delay = config.source_request_delay() if delay is None else delay
    source_name = source.source_name
    checked_at = clock.now()
    report = {
        "status": "ok", "source": source_name, "pages_checked": 0, "found": 0, "imported": 0,
        "updated": 0, "unchanged": 0, "detail_failed": 0, "cancelled": 0, "error": None,
        "detail_errors": [], "touched_job_ids": [],
    }
    fetch_warnings: list[str] = []
    rejected_job_ids = set(db.scalars(select(UserVerification.job_id).where(
        UserVerification.position_id == "", UserVerification.decision == "not_eligible",
    )).all())
    retry_document_job_ids = set(db.scalars(select(JobDocument.job_id).where(
        JobDocument.status == "unavailable", JobDocument.checked_at < checked_at - timedelta(hours=20),
    )).all())
    try:
        listings = source.fetch_listings()
        fetch_warnings = list(getattr(source, "fetch_warnings", []) or [])
        report["fetch_warnings"] = fetch_warnings
        report["pages_checked"] = getattr(source, "pages_checked", 0)
        report["found"] = len(listings)
        previous_found = db.scalar(
            select(SourceSyncHistory.found).where(
                SourceSyncHistory.source_key == source_key, SourceSyncHistory.status.in_(("ok", "partial")),
            ).order_by(SourceSyncHistory.checked_at.desc()).limit(1)
        ) or 0
        if not listings and previous_found and not getattr(source, "allow_empty", False):
            # Önceki taramada ilan varken sıfır sonuç, sessizce "başarılı" sayılmaz.
            report["empty_warning"] = (
                f"Önceki taramada {previous_found} ilan bulunmuştu, bu taramada hiç ilan bulunamadı. "
                "Kaynakta gerçekten ilan olmayabilir ya da sayfa yapısı değişmiş olabilir; mevcut kayıtlar korunuyor."
            )

        cancellations: list[dict] = []
        for index, item in enumerate(listings):
            if on_progress:
                on_progress(source_name, index + 1, len(listings))
            detail_url = str(item.get("detail_url") or "").strip()
            external = str(item.get("external_id") or detail_url).strip()
            if not detail_url or not external or not str(item.get("title") or "").strip():
                report["detail_failed"] += 1
                continue
            if item.get("is_cancellation") or "iptal ilan" in normalize_text(str(item.get("title"))):
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

            # Taranmış ve OCR'la da okunamayan belge her taramada yeniden denenmez ("OCR'la yeniden dene" ile denenir).
            still_open = job.application_deadline is None or job.application_deadline >= clock.today()
            needs_detail = (
                job.id not in rejected_job_ids
                and (
                    created or listing.list_hash != list_hash or listing.status not in ("complete", "unreadable")
                    # Eki daha önce indirilemeyen açık ilan, günde en çok bir kez yeniden denenir.
                    or (job.id in retry_document_job_ids and still_open)
                )
            )
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
                    _retire_unrelated_documents(db, job, details)
                    listing.content_hash = str(details.get("content_hash") or "")[:64]
                    listing.status = "complete"
                    listing.raw_payload = json.dumps(
                        {"listing": item, "detail_keys": sorted(details)}, ensure_ascii=False, sort_keys=True, default=str,
                    )[:20000]
                except Exception as error:  # tek ilanın hatası taramayı durdurmaz
                    from .documents import ScannedDocumentError

                    listing.status = "unreadable" if isinstance(error, ScannedDocumentError) else "detail_failed"
                    listing.raw_payload = json.dumps({"error": str(error)[:400]}, ensure_ascii=False)
                    report["detail_failed"] += 1
                    report["detail_errors"].append({"url": user_url, "title": job.title, "error": str(error)[:300]})
                    logger.warning("Detail fetch failed for %s: %s", detail_url, error)
                if delay:
                    time.sleep(delay)
            listing.list_hash = list_hash
            sync_job_events(db, job)

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
        report["status"] = (
            "warning" if report.get("empty_warning") else "partial"
            if report["detail_failed"] or fetch_warnings else "ok"
        )
    except Exception as error:
        db.rollback()
        report["status"] = "error"
        # Browser/network timeout exceptions can have an empty str(); preserve the type
        # so the source card and sync history still explain what actually failed.
        detail = str(error).strip() or f"{type(error).__name__} (hata iletisi boş)"
        report["error"] = detail[:500]
        report["error_kind"] = classify_error(error)
        logger.warning("Source %s failed: %s", source_key, detail)

    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()

    summary_error = report["error"] or report.get("empty_warning") or "; ".join(
        f"{item['title'][:60]}: {item['error']}" for item in report["detail_errors"][:5]
    ) or "; ".join(fetch_warnings[:5])
    db.add(SourceSyncHistory(
        source_key=source_key, source_name=source_name, status=report["status"], checked_at=checked_at,
        pages_checked=report["pages_checked"], found=report["found"], imported=report["imported"],
        updated=report["updated"], unchanged=report["unchanged"], detail_failed=report["detail_failed"],
        error=summary_error or "", error_kind=report.get("error_kind", ""), origin=config.scan_origin(),
    ))
    db.commit()
    return report


# ---------------------------------------------------------------------------
# Tarama kilidi: aynı veritabanına yazan bütün tarayıcılar için tek seferde tek tarama
# ---------------------------------------------------------------------------

LOCK_NAME = "source-sync"
LOCK_LEASE = timedelta(minutes=20)


def acquire_scan_lock(db: Session, owner: str, *, now: datetime | None = None) -> bool:
    """Kilidi alır; başka bir tarama sürüyorsa False döner. Süresi dolmuş (sahibi çökmüş) kilit devralınır."""
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from .models import ScanLock

    now = now or clock.now()
    taken = db.execute(
        update(ScanLock).where(ScanLock.name == LOCK_NAME, ScanLock.expires_at < now)
        .values(owner=owner, acquired_at=now, expires_at=now + LOCK_LEASE)
    ).rowcount
    if taken:
        db.commit()
        return True
    if db.get(ScanLock, LOCK_NAME) is not None:
        db.rollback()
        return False
    try:
        db.add(ScanLock(name=LOCK_NAME, owner=owner, acquired_at=now, expires_at=now + LOCK_LEASE))
        db.commit()
        return True
    except IntegrityError:  # aynı anda başka bir süreç ekledi
        db.rollback()
        return False


def extend_scan_lock(db: Session, owner: str) -> None:
    from sqlalchemy import update

    from .models import ScanLock

    db.execute(update(ScanLock).where(ScanLock.name == LOCK_NAME, ScanLock.owner == owner)
               .values(expires_at=clock.now() + LOCK_LEASE))
    db.commit()


def release_scan_lock(db: Session, owner: str) -> None:
    from sqlalchemy import delete

    from .models import ScanLock

    db.rollback()
    db.execute(delete(ScanLock).where(ScanLock.name == LOCK_NAME, ScanLock.owner == owner))
    db.commit()


def backfill_application_dates(db: Session) -> int:
    """Başvuru tarihi boş kalan ilanlarda tarihi, saklanan ilan metninden ve belgelerinden yeniden arar.

    Yalnızca boş alan doldurulur; kaynağın verdiği ya da daha önce bulunan tarih değiştirilmez.
    """
    filled = 0
    jobs = db.scalars(select(Job).where(
        Job.sector == "public", Job.archived_reason == "", Job.application_deadline.is_(None),
    )).all()
    for job in jobs:
        documents = db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all()
        text = "\n".join(filter(None, [job.description or "", *[
            document.extracted_text for document in documents
            if document.extracted_text and document.ocr_confidence is None and document.status != "obsolete"
        ]]))
        if len(text) < 80:
            continue
        start, end = application_window_from_text(text)
        end = end or application_deadline_from_text(text)
        if end is None:
            worded_start, end = worded_application_window(text)
            start = start or worded_start
        if end is None:
            continue
        job.application_deadline = end
        if job.application_start is None and start is not None and start <= end:
            job.application_start = start
        job.updated_at = clock.now()
        filled += 1
    if filled:
        db.commit()
    return filled


class ScanAlreadyRunning(RuntimeError):
    pass


def run_sync_locked(db: Session, *, on_progress=None, **kwargs) -> dict:
    """Kilit altında tarama. Başka bir tarama (başka bir sunucuda bile olsa) sürüyorsa ScanAlreadyRunning."""
    import os
    import socket

    owner = f"{config.scan_origin()}:{socket.gethostname()}:{os.getpid()}:{time.time():.0f}"[:120]
    if not acquire_scan_lock(db, owner):
        raise ScanAlreadyRunning("Başka bir tarama zaten sürüyor.")
    last_beat = time.monotonic()

    def progress(source: str, current: int, total: int) -> None:
        nonlocal last_beat
        if time.monotonic() - last_beat > 60:
            last_beat = time.monotonic()
            try:
                extend_scan_lock(db, owner)
            except Exception:  # kira uzatılamazsa tarama sürer; kilit süresi dolunca boşalır
                db.rollback()
        if on_progress:
            on_progress(source, current, total)

    try:
        return run_sync(db, on_progress=progress, **kwargs)
    finally:
        release_scan_lock(db, owner)


def run_sync(db: Session, *, registry: dict | None = None, on_progress=None, scan_documents: bool = True,
             check_results: bool = True) -> dict:
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
        today = clock.today()
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

    backfill_application_dates(db)
    refresh_all_events(db)
    invalidate_cache()
    # Sonuç duyuruları ve duyuru akışları (YLSY) her taramanın parçasıdır.
    result_check = announcement_check = None
    if check_results and not config.env_flag("CAREERPILOT_DISABLE_RESULT_CHECK"):
        from .results import check_results as run_result_check
        from .ylsy import sync_ylsy

        try:
            result_check = run_result_check(db, on_progress=on_progress)
        except Exception as error:  # sonuç takibindeki hata ilan taramasını bozmaz
            db.rollback()
            logger.exception("Result check failed")
            result_check = {"error": str(error)[:300]}
        if on_progress:
            on_progress("YLSY duyuruları", 0, 0)
        announcement_check = sync_ylsy(db)
    notifications = process_notifications(db)
    for report in results.values():
        report.pop("touched_job_ids", None)
    return {
        "success": all(report["status"] == "ok" for report in results.values()),
        "results": results,
        "document_scan": document_scan,
        "result_check": result_check,
        "announcement_check": announcement_check,
        "notifications": notifications,
    }


def _move_user_data(db: Session, source_id: int, target_id: int) -> None:
    """Kopya kayıt arşivlenirken kullanıcının takip durumu, notu ve doğrulamaları asıl kayda taşınır."""
    from .models import UserJobState, UserVerification

    state = db.get(UserJobState, source_id)
    if state is not None and db.get(UserJobState, target_id) is None:
        db.add(UserJobState(job_id=target_id, tracking=state.tracking, notes=state.notes, updated_at=state.updated_at))
        db.delete(state)
    taken = {item.position_id for item in db.scalars(select(UserVerification).where(UserVerification.job_id == target_id)).all()}
    for item in db.scalars(select(UserVerification).where(UserVerification.job_id == source_id)).all():
        if item.position_id == "" and "" not in taken:
            item.job_id = target_id


def _listing_for(db: Session, job: Job) -> SourceListing | None:
    return db.scalar(select(SourceListing).where(SourceListing.job_id == job.id).order_by(SourceListing.id.desc()).limit(1))


def _fresh_detail_url(source, listing: SourceListing) -> str:
    """Detay bağlantısı oturuma bağlı kaynaklarda (SBB) güncel bağlantıyı listeden bulur."""
    if listing.source_key != "sbb":
        return listing.official_url
    for item in source.fetch_listings():
        if str(item.get("external_id")) == listing.external_id:
            return str(item["detail_url"])
    raise RuntimeError("İlan artık kaynak listesinde görünmüyor.")


def refetch_job(db: Session, job: Job) -> dict:
    """Tek ilanın ayrıntısını (gerekirse OCR ile) yeniden okur. "OCR'la yeniden dene" bunu çağırır."""
    listing = _listing_for(db, job)
    if listing is None:
        raise RuntimeError("Bu ilan bir kaynak taramasından gelmiyor.")
    source = get_source_registry()[listing.source_key]
    try:
        details = source.fetch_detail(_fresh_detail_url(source, listing))
        if len(str(details.get("source_text") or "").strip()) < 80:
            raise ValueError("Ayrıştırılabilir ilan metni bulunamadı.")
        now = clock.now()
        _apply_detail(job, {}, details)
        job.updated_at = now
        db.flush()
        if details.get("document"):
            _store_document(db, job, details["document"], now)
        listing.status = "complete"
        listing.content_hash = str(details.get("content_hash") or "")[:64]
        sync_job_events(db, job)
        db.commit()
        confidence = (details.get("document") or {}).get("parsed", {}).get("ocr_confidence")
        return {"status": "ocr" if confidence is not None else "read", "ocr_confidence": confidence}
    except Exception as error:
        from .documents import ScannedDocumentError

        db.rollback()
        listing.status = "unreadable" if isinstance(error, ScannedDocumentError) else "detail_failed"
        listing.raw_payload = json.dumps({"error": str(error)[:400]}, ensure_ascii=False)
        db.commit()
        return {"status": "failed", "error": str(error)[:300]}
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()


def download_official_pdf(db: Session, job: Job) -> bytes:
    """İlanın resmî PDF'ini kaynağından indirir (uygulama içinde göstermek için; saklanmaz)."""
    from . import tls
    from .sources.base import DEFAULT_HEADERS

    listing = _listing_for(db, job)
    if listing is not None and listing.source_key == "sbb":
        source = get_source_registry()["sbb"]
        url = _fresh_detail_url(source, listing)
        response = source._session.get(url, timeout=(8, 60), headers={**DEFAULT_HEADERS, "Referer": source.base_url})
        body = response.content
    else:
        candidates = [listing.official_url] if listing is not None else []
        candidates += [doc.document_url for doc in db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all()]
        url = next((item for item in candidates if item and ".pdf" in item.casefold()), None)
        if url is None:
            raise RuntimeError("Bu ilanın PDF belgesi yok.")
        from .documents import fetch_url

        try:
            body = fetch_url(url)["body"]
        except Exception:
            body = tls.get(url, headers=DEFAULT_HEADERS, timeout=(8, 60)).content
    if not body.startswith(b"%PDF-"):
        raise RuntimeError("Kaynak bu ilan için PDF döndürmedi.")
    return body


def cleanup_legacy_rows(db: Session) -> dict:
    """Eski sürümlerden kalan ilan olmayan kayıtları ve aynı kaynaktaki kopyaları arşivler.

    Hiçbir kayıt silinmez: `archived_reason` doldurulur; kayıt havuzda kalır ama değerlendirilmez.
    """
    from .sources.yerel_yonetimler import parse_announcement_title

    archived = 0
    jobs = list(db.scalars(select(Job).where(Job.sector == "public", Job.archived_reason == "")).all())
    groups: dict[tuple, list[Job]] = {}
    for job in jobs:
        if job.source_name in ("Manuel Giriş", "Toplu Yükleme"):
            continue
        if "iptal ilan" in normalize_text(job.title) and job.source_name != "Yerel Yönetimler Genel Müdürlüğü":
            job.archived_reason = "İptal duyurusu (ilan değil)"
            archived += 1
            continue
        if job.source_name == "Yerel Yönetimler Genel Müdürlüğü":
            parsed = parse_announcement_title(job.title)
            if parsed["is_cancellation"]:
                job.archived_reason = "İptal duyurusu (ilan değil)"
            elif not parsed["is_recruitment"]:
                job.archived_reason = "İlan değil: kaynak sitesinin bilgi sayfası"
            if job.archived_reason:
                archived += 1
                continue
        if job.is_employment != _is_employment(job.title):
            job.is_employment = _is_employment(job.title)
        title_key = re.sub(r"[^a-z0-9]+", " ", normalize_text(job.title)).strip()
        groups.setdefault((job.source_name, organization_key(job.organization), title_key, job.application_deadline), []).append(job)
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda job: (len(job.description or ""), -job.id))
        for job in members:
            if job.id == keep.id:
                continue
            job.archived_reason = f"Aynı kaynaktaki kopya kayıt (asıl kayıt #{keep.id})"
            for listing in db.scalars(select(SourceListing).where(SourceListing.job_id == job.id)).all():
                listing.job_id = keep.id
            _move_user_data(db, job.id, keep.id)
            archived += 1
    db.commit()
    return {"archived": archived}


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
                running=True, trigger=trigger, started_at=clock.now().isoformat(timespec="seconds"),
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
                self.state["report"] = run_sync_locked(db, on_progress=self._progress)
        except ScanAlreadyRunning as running:
            self.state["error"] = f"{running} Bittiğinde sonuçlar burada görünecek."
        except Exception as error:  # pragma: no cover - beklenmeyen hata durumunu kullanıcıya göster
            logger.exception("Sync run failed")
            self.state["error"] = str(error)[:500]
        finally:
            self.state.update(
                running=False, progress=None, finished_at=clock.now().isoformat(timespec="seconds"),
            )

    # ---- otomatik tarama ----
    def start_scheduler(self) -> None:
        interval = config.sync_interval_hours()
        if interval <= 0 or self._scheduler is not None:
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
                due = last is None or clock.now() - last >= timedelta(hours=interval_hours)
                if due:
                    self.start("auto")
            except Exception:  # pragma: no cover
                logger.exception("Scheduler check failed")
            if self._stop.wait(600):
                return


sync_manager = SyncManager()


def main(argv: list[str] | None = None) -> int:
    """Komut satırından tek seferlik tarama: `python -m backend.sync [--no-notify] [--summary dosya]`."""
    import argparse
    import os

    from .database import Base, SessionLocal, engine
    from .migrate import migrate

    parser = argparse.ArgumentParser(description="Bütün kaynakları tarar ve bildirimleri üretir.")
    parser.add_argument("--no-notify", action="store_true", help="E-posta/Telegram gönderme (bildirim kayıtları yine oluşur).")
    parser.add_argument("--summary", help="Markdown özetinin yazılacağı dosya (ör. GitHub Actions özeti).")
    args = parser.parse_args(argv)

    if args.no_notify:
        import os

        os.environ["CAREERPILOT_NOTIFY_DISABLED"] = "true"
    migrate()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        cleanup_legacy_rows(db)
        try:
            report = run_sync_locked(db)
        except ScanAlreadyRunning as running:
            print(str(running))
            return 0

    lines = ["| Kaynak | Durum | Bulunan | Yeni | Güncellenen | Okunamayan | Not |", "|---|---|---|---|---|---|---|"]
    for item in report["results"].values():
        note = (item.get("error") or item.get("empty_warning") or "").replace("|", "/")[:160]
        lines.append(
            f"| {item['source']} | {item['status']} | {item['found']} | {item['imported']} | {item['updated']} "
            f"| {item['detail_failed']} | {note} |"
        )
    notifications = report.get("notifications") or {}
    lines.append("")
    results = report.get("result_check") or {}
    if results.get("error"):
        lines.append(f"Sonuç takibi çalışmadı: {results['error']}")
    elif results:
        lines.append(
            f"Sonuç takibi: {results['tracked']} ilan izleniyor · {results['checked']} kontrol edildi · "
            f"{results['found']} yeni sonuç duyurusu · {results['errors']} kaynak kontrol edilemedi · "
            f"{results['no_source']} ilanda resmî adres yok · {results['skipped']} sonraki taramaya kaldı"
        )
    ylsy = report.get("announcement_check") or {}
    if ylsy:
        lines.append(f"YLSY duyuruları: {ylsy.get('status')} · {ylsy.get('new', 0)} yeni" + (f" · {ylsy['error']}" if ylsy.get("error") else ""))
    lines.append(f"Yeni bildirim: {notifications.get('created', 0)} · Kanallar: {notifications.get('channels') or 'gönderim yok'}")
    summary = "\n".join(lines)
    print(summary)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("## CareerPilot taraması\n\n" + summary + "\n")
    # Kaynakların tamamı hata verdiyse iş başarısız sayılır; kısmi sonuçlar başarılıdır.
    statuses = [item["status"] for item in report["results"].values()]
    successful_source = any(status in {"ok", "partial", "warning"} for status in statuses)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"successful_source={'true' if successful_source else 'false'}\n")
    return 1 if statuses and not successful_source else 0


if __name__ == "__main__":
    raise SystemExit(main())
