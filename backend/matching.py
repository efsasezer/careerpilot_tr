"""Kayıtlı ilanları aday profiliyle eşleştirip API ve bildirimler için hazırlar."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import re
import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .eligibility import (
    build_candidate_profile,
    classify_public_job,
    detect_application_status,
    detect_recruitment_method,
    normalize_text,
)
from .models import (
    CandidateProfile, DocumentPosition, Job, JobDocument, JobDocumentScan, JobEvent,
    UserJobState, UserVerification,
)
from .sync import _role_words, organization_key

CATEGORY_ORDER = {"UYGUN": 0, "POTANSİYEL OLARAK UYGUN": 1, "UYGUN DEĞİL": 2}
CITIES = (
    "adana", "adiyaman", "afyonkarahisar", "agri", "aksaray", "amasya", "ankara", "antalya", "ardahan", "artvin",
    "aydin", "balikesir", "bartin", "batman", "bayburt", "bilecik", "bingol", "bitlis", "bolu", "burdur", "bursa",
    "canakkale", "cankiri", "corum", "denizli", "diyarbakir", "duzce", "edirne", "elazig", "erzincan", "erzurum",
    "eskisehir", "gaziantep", "giresun", "gumushane", "hakkari", "hatay", "igdir", "isparta", "istanbul", "izmir",
    "kahramanmaras", "karabuk", "karaman", "kars", "kastamonu", "kayseri", "kilis", "kirikkale", "kirklareli",
    "kirsehir", "kocaeli", "konya", "kutahya", "malatya", "manisa", "mardin", "mersin", "mugla", "mus", "nevsehir",
    "nigde", "ordu", "osmaniye", "rize", "sakarya", "samsun", "sanliurfa", "siirt", "sinop", "sirnak", "sivas",
    "tekirdag", "tokat", "trabzon", "tunceli", "usak", "van", "yalova", "yozgat", "zonguldak",
)


def _preferred_cities(profile: dict) -> list[str]:
    text = normalize_text(profile.get("preferred_locations") or "")
    if not text.strip() or "turkiye geneli" in text or "tum" in text.split() or "fark etmez" in text:
        return []
    return [part.strip() for part in re.split(r"[,;/\n]", text) if part.strip()]


def location_match(preferred: list[str], *texts: str) -> bool | None:
    """True: tercih edilen şehirde, False: başka şehirde, None: şehir bilinmiyor/tercih yok."""
    if not preferred:
        return None
    haystack = normalize_text(" ".join(text or "" for text in texts))
    if any(re.search(rf"(?<![a-z]){re.escape(city)}(?![a-z])", haystack) for city in preferred):
        return True
    known = any(re.search(rf"(?<![a-z]){city}(?![a-z])", haystack) for city in CITIES)
    return False if known else None


def _base_position(job: Job) -> dict:
    title = job.title or ""
    return {
        "sub_id": str(job.id),
        "parent_id": job.id,
        "organization": job.organization or "Kurum belirtilmemiş",
        "title": title,
        "position": title.split(" - ")[-1] if " - " in title else title,
        "quota": job.quota or None,
        "city": job.city or None,
        "kpss_score_type": job.kpss_score_type or "",
        "kpss_min_score": job.kpss_min_score,
        "education_requirement": job.education_requirement or "",
        "qualification_codes": job.qualification_codes or "",
        "description": job.description or "",
        "source_url": job.source_url or None,
        "source_name": job.source_name or "Kaynak belirtilmemiş",
        "application_start": job.application_start,
        "application_deadline": job.application_deadline,
        "recruitment_method": job.recruitment_method or detect_recruitment_method(title, job.description or ""),
        "employment_type": job.employment_type or "",
    }


def decompose_job_positions(job: Job, documents: list[JobDocument], positions_by_document: dict) -> list[dict]:
    """Belgedeki kadro tablosu varsa her satırı ayrı pozisyon olarak döndürür."""
    base = _base_position(job)
    shared_text = "\n".join(document.shared_requirements for document in documents if document.shared_requirements)
    rows = [
        (document, position)
        for document in documents
        for position in positions_by_document.get(document.id, [])
    ]
    # Güvenlik: farklı unvanlı satırların hepsi aynı nitelik metnini taşıyorsa tablo yanlış
    # ayrıştırılmıştır. Satırlar kullanılmaz; ilan bütün metniyle tek kayıt olarak değerlendirilir.
    requirement_texts = {normalize_text(row.education_requirement) for _, row in rows if row.education_requirement}
    titles = {normalize_text(row.position_title) for _, row in rows}
    if len(rows) >= 3 and len(requirement_texts) == 1 and len(titles) > 1:
        rows = []
        base["table_unreliable"] = True

    if not rows:
        # Kadro tablosu ayrıştırılamadıysa ek belgelerin metni de değerlendirmeye katılır.
        extra = [
            document.extracted_text for document in documents
            if document.extracted_text and document.extracted_text[:200] not in base["description"]
        ]
        if extra:
            base["description"] = "\n".join(filter(None, (base["description"], *extra)))[:120_000]
        return [base]

    # Aynı tablo iki ayrı ekte yer alıyorsa satırlar bir kez sayılır; aynı belgedeki
    # nitelikleri aynı iki kadro (ör. farklı dereceler) ise ayrı kadrolardır.
    result, seen = [], {}
    for document, row in rows:
        title = row.position_title or row.education_requirement or "Kadro satırı"
        key = normalize_text("|".join((
            title, row.education_requirement, row.quota, row.kpss_score_type, str(row.kpss_min_score), row.city,
        )))
        if seen.setdefault(key, document.id) != document.id:
            continue
        result.append({
            **base,
            "sub_id": f"{job.id}-document-{document.id}-{row.row_index}",
            "title": f"{job.title} — {title}",
            "position": title[:200],
            "quota": row.quota or job.quota or None,
            "city": row.city or job.city or None,
            "kpss_score_type": row.kpss_score_type or job.kpss_score_type or "",
            "kpss_min_score": row.kpss_min_score if row.kpss_min_score is not None else job.kpss_min_score,
            "education_requirement": row.education_requirement or job.education_requirement or "",
            "qualification_codes": row.qualification_codes or job.qualification_codes or "",
            # Satırın kendi şartları + bütün pozisyonlar için ortak şartlar; diğer satırların
            # bölümleri bu pozisyona karışmasın diye ilanın tam metni eklenmez.
            "description": "\n".join(filter(None, (shared_text, row.requirements_text))),
            "position_specific": bool(row.education_requirement),
            "source_document_id": document.id,
            "basis": {"document_title": document.title or "Resmî ilan metni", "document_url": document.document_url, "table_row": row.row_index},
            "written_exam_invite_text": row.written_exam_invite_text,
            "written_exam_invite_count": row.written_exam_invite_count,
        })
    return result


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _document_review(scan, documents, positions_by_document) -> dict:
    return {
        "status": scan.status if scan else "not_scanned",
        "error": scan.error if scan else "",
        "checked_at": _iso(scan.checked_at) if scan else None,
        "documents": [
            {
                "id": document.id,
                "title": document.title,
                "url": document.document_url,
                "status": document.status,
                "content_hash": document.content_hash,
                "parsed_content_hash": document.parsed_content_hash,
                "error": document.error,
                "checked_at": _iso(document.checked_at),
                "positions": [
                    {
                        "row_index": row.row_index,
                        "position_title": row.position_title,
                        "education_requirement": row.education_requirement,
                        "quota": row.quota,
                        "kpss_score_type": row.kpss_score_type,
                        "kpss_min_score": row.kpss_min_score,
                        "city": row.city,
                        "qualification_codes": row.qualification_codes,
                        "written_exam_invite_text": row.written_exam_invite_text,
                        "written_exam_invite_count": row.written_exam_invite_count,
                    }
                    for row in positions_by_document.get(document.id, [])
                ],
            }
            for document in documents
        ],
    }


_GENERIC_TITLE_STEMS = {
    "alacak", "alimi", "alim", "ilani", "ilan", "sinavi", "sinav", "giris", "person", "sozles", "memur",
    "yili", "baskan", "genel", "mudurl", "univer", "rektor", "bakanl", "kurumu", "kurulu", "belediy",
    "duyuru", "icin", "uzere", "temin", "edilec", "adet", "proje", "bazli", "turkiy", "cumhur",
}


def _title_stems(job: Job) -> set[str]:
    words = re.sub(r"[^a-z]+", " ", normalize_text(f"{job.title}")).split()
    return {word[:6] for word in words if len(word) >= 5} - _GENERIC_TITLE_STEMS


def _roles_compatible(first: set[str], second: set[str]) -> bool:
    """Bir kaynak "memur", diğeri "zabıta memuru" yazabilir; ikisi aynı ilandır."""
    if first == second:
        return True
    civil = {"memur", "zabita", "itfaiye"}
    return ("memur" in first or "memur" in second) and first <= civil and second <= civil


def _duplicate_groups(jobs: list[Job]) -> tuple[set[int], dict[int, list[Job]]]:
    """Aynı ilanın farklı kaynaklardaki kopyalarını bulur: (gizlenecek id'ler, birincil id -> kopyalar)."""
    by_org: dict[str, list[Job]] = {}
    for job in jobs:
        key = organization_key(job.organization)
        if key and job.is_employment:
            by_org.setdefault(key, []).append(job)

    hidden: set[int] = set()
    copies: dict[int, list[Job]] = {}
    for members in by_org.values():
        if len(members) < 2:
            continue
        clusters: list[list[Job]] = []
        # En ayrıntılı kayıt kümenin birincili olur.
        for job in sorted(members, key=lambda item: (-len(item.description or ""), item.id)):
            roles = _role_words(job.title)
            for cluster in clusters:
                primary = cluster[0]
                if any(other.source_name == job.source_name for other in cluster):
                    continue  # aynı kaynaktaki iki kayıt farklı ilanlardır
                same_deadline = job.application_deadline == primary.application_deadline
                missing_deadline = job.application_deadline is None or primary.application_deadline is None
                if (same_deadline and job.application_deadline is not None) or (
                    missing_deadline and any(
                        _roles_compatible(roles, _role_words(other.title)) or _title_stems(job) & _title_stems(other)
                        for other in cluster
                    )
                ):
                    cluster.append(job)
                    break
            else:
                clusters.append([job])
        for cluster in clusters:
            for job in cluster[1:]:
                hidden.add(job.id)
                copies.setdefault(cluster[0].id, []).append(job)
    # Aynı ilan, kaynaklarda farklı kurum adıyla yayımlanabilir (bakanlık / bağlı kurul).
    # Başlangıç ve bitiş tarihleri aynı, başlıkları en az iki ayırt edici sözcük paylaşan,
    # farklı kaynaklardaki kayıtlar da birleştirilir.
    remaining = [job for job in jobs if job.id not in hidden and job.is_employment
                 and job.application_start and job.application_deadline]
    by_window: dict[tuple, list[Job]] = {}
    for job in remaining:
        by_window.setdefault((job.application_start, job.application_deadline), []).append(job)
    for members in by_window.values():
        if len(members) < 2:
            continue
        for job in sorted(members, key=lambda item: (-len(item.description or ""), item.id)):
            if job.id in hidden:
                continue
            for other in members:
                if other.id == job.id or other.id in hidden or other.id in copies:
                    continue
                family = [job, *copies.get(job.id, [])]
                if any(member.source_name == other.source_name for member in family):
                    continue
                if len(_title_stems(job) & _title_stems(other)) >= 2:
                    hidden.add(other.id)
                    copies.setdefault(job.id, []).append(other)
    return hidden, copies


DECISION_CATEGORY = {"eligible": "UYGUN", "not_eligible": "UYGUN DEĞİL"}


def job_content_version(job: Job, documents: list[JobDocument], positions_by_document: dict) -> tuple[str, dict]:
    """İlanın metni, kadro tablosu ve tarihlerinin özeti. Elle doğrulama bu sürüme bağlanır."""
    rows = [
        "|".join(str(value or "") for value in (
            row.position_title, row.education_requirement, row.quota, row.kpss_score_type, row.kpss_min_score, row.city,
        ))
        for document in documents for row in positions_by_document.get(document.id, [])
    ]
    snapshot = {
        "title": job.title or "",
        "application_start": job.application_start.isoformat() if job.application_start else None,
        "application_deadline": job.application_deadline.isoformat() if job.application_deadline else None,
        "text_hash": sha256((job.description or "").encode("utf-8")).hexdigest(),
        "positions_hash": sha256("\n".join(rows).encode("utf-8")).hexdigest(),
        "position_count": len(rows),
        "status": job.status or "",
    }
    digest = sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return digest, snapshot


_CHANGE_LABELS = {
    "title": "başlık", "application_start": "başvuru başlangıcı", "application_deadline": "son başvuru tarihi",
    "text_hash": "ilan metni", "positions_hash": "kadro tablosu", "position_count": "kadro sayısı", "status": "ilan durumu",
}


def content_changes(old_snapshot: str, current: dict) -> list[str]:
    try:
        old = json.loads(old_snapshot or "{}")
    except ValueError:
        old = {}
    changes = []
    for key, label in _CHANGE_LABELS.items():
        if key in old and old[key] != current.get(key):
            if key in ("application_start", "application_deadline"):
                changes.append(f"{label}: {old[key] or 'yok'} → {current.get(key) or 'yok'}")
            else:
                changes.append(label)
    return changes or ["ilan içeriği"]


def _preference_status(profile: dict, preferred: list[str], *texts: str) -> tuple[bool | None, bool]:
    """(tercih edilen şehirde mi, tercih dışı mı). Resmî uygunluğu değiştirmez."""
    match = location_match(preferred, *texts)
    haystack = normalize_text(" ".join(text or "" for text in texts))
    excluded = [normalize_text(str(item)).strip() for item in (profile.get("preferences") or {}).get("excluded", []) if str(item).strip()]
    unwanted = any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", haystack) for word in excluded)
    return match, bool(unwanted or match is False)


_CACHE: dict[tuple, dict] = {}
_BUILD_LOCK = threading.RLock()


def invalidate_cache() -> None:
    """Profil, takip veya ilan verisi değiştiğinde çağrılır."""
    _CACHE.clear()


def _data_version(db: Session, profile) -> tuple:
    """Eşleştirme sonucunu etkileyen verinin ucuz bir parmak izi (önbellek anahtarı)."""
    jobs = db.execute(select(func.count(Job.id), func.max(Job.updated_at), func.max(Job.created_at), func.max(Job.id))).one()
    documents = db.execute(select(func.count(JobDocument.id), func.max(JobDocument.checked_at))).one()
    positions = db.scalar(select(func.count(DocumentPosition.id)))
    tracked = db.execute(
        select(Job.id, Job.status, Job.cancellation_notice)
        .where((Job.status == "İptal edildi") | (Job.cancellation_notice != "")).order_by(Job.id)
    ).all()
    user_side = (
        db.execute(select(func.count(UserJobState.job_id), func.max(UserJobState.updated_at))).one(),
        db.execute(select(func.count(UserVerification.id), func.max(UserVerification.verified_at))).one(),
        db.execute(select(func.count(JobEvent.id), func.max(JobEvent.updated_at))).one(),
    )
    return (
        tuple(jobs), tuple(documents), positions, tuple(map(tuple, tracked)), tuple(map(tuple, user_side)),
        getattr(profile, "educations", None), getattr(profile, "experiences", None), getattr(profile, "preferences", None),
        getattr(profile, "birth_date", None), getattr(profile, "experience_state", None),
        getattr(profile, "updated_at", None), getattr(profile, "kpss_scores", None), getattr(profile, "department", None),
    )


def build_matches(db: Session, *, full: bool = True, today: date | None = None, only_job_ids: list[int] | None = None) -> dict:
    """Bütün kamu ilanlarını profile göre sınıflandırır.

    full=False olduğunda uzun metinler (ilan açıklaması, belge incelemesi) yanıta eklenmez.
    """
    today = today or date.today()
    stored_profile = db.get(CandidateProfile, 1)
    cache_key = None
    if only_job_ids is None:
        cache_key = (str(db.get_bind().url), full, today, _data_version(db, stored_profile))
        if cache_key in _CACHE:
            return _CACHE[cache_key]
        # Aynı anda gelen istekler hesabı bir kez yapar; diğerleri sonucu önbellekten alır.
        with _BUILD_LOCK:
            if cache_key in _CACHE:
                return _CACHE[cache_key]
            return _build_matches(db, full=full, today=today, cache_key=cache_key, stored_profile=stored_profile)
    return _build_matches(db, full=full, today=today, cache_key=None, stored_profile=stored_profile, only_job_ids=only_job_ids)


def _build_matches(db: Session, *, full: bool, today: date, cache_key, stored_profile, only_job_ids: list[int] | None = None) -> dict:
    profile = build_candidate_profile(stored_profile)
    preferred = _preferred_cities(profile)
    preferred += [
        normalize_text(str(city)).strip() for city in (profile.get("preferences") or {}).get("cities", [])
        if str(city).strip() and normalize_text(str(city)).strip() not in preferred
    ]
    states = {state.job_id: state for state in db.scalars(select(UserJobState)).all()}
    verifications: dict[int, dict[str, UserVerification]] = {}
    for record in db.scalars(select(UserVerification)).all():
        verifications.setdefault(record.job_id, {})[record.position_id] = record

    jobs = list(db.scalars(
        select(Job).where(Job.sector == "public", Job.archived_reason == "").order_by(Job.id.desc())
    ).all())
    job_ids = [job.id for job in jobs]
    scans = {
        scan.job_id: scan
        for scan in db.scalars(select(JobDocumentScan).where(JobDocumentScan.job_id.in_(job_ids))).all()
    } if job_ids else {}
    documents_by_job: dict[int, list[JobDocument]] = {}
    documents = list(db.scalars(
        select(JobDocument).where(JobDocument.job_id.in_(job_ids)).order_by(JobDocument.id)
    ).all()) if job_ids else []
    for document in documents:
        documents_by_job.setdefault(document.job_id, []).append(document)
    positions_by_document: dict[int, list[DocumentPosition]] = {}
    document_ids = [document.id for document in documents]
    if document_ids:
        for row in db.scalars(
            select(DocumentPosition).where(DocumentPosition.document_id.in_(document_ids))
            .order_by(DocumentPosition.document_id, DocumentPosition.row_index)
        ).all():
            positions_by_document.setdefault(row.document_id, []).append(row)

    hidden, copies = _duplicate_groups(jobs)
    if only_job_ids is not None:
        hidden = set()
        jobs = [job for job in jobs if job.id in set(only_job_ids)]
    counts = {"UYGUN": 0, "POTANSİYEL OLARAK UYGUN": 0, "UYGUN DEĞİL": 0}
    items, opportunities = [], []

    for job in jobs:
        if job.id in hidden:
            continue
        cancelled = job.status == "İptal edildi"
        job_status = "İptal Edildi" if cancelled else detect_application_status(job.application_start, job.application_deadline, today)

        if not job.is_employment:
            opportunities.append({
                "id": job.id,
                "title": job.title,
                "organization": job.organization,
                "city": job.city or "",
                "source_url": job.source_url or None,
                "source_name": job.source_name or "Kaynak belirtilmemiş",
                "application_start": _iso(job.application_start),
                "application_deadline": _iso(job.application_deadline),
                "application_status": job_status,
                "category": "Eğitim & Burs Fırsatı",
                "description": (job.description or "")[: None if full else 600],
            })
            continue

        job_documents = documents_by_job.get(job.id, [])
        review = _document_review(scans.get(job.id), job_documents, positions_by_document) if full else None
        duplicates = copies.get(job.id, [])
        also_listed = [
            {"source_name": other.source_name, "source_url": other.source_url or None} for other in duplicates
        ]
        state = states.get(job.id) or next((states[other.id] for other in duplicates if other.id in states), None)
        tracking = state.tracking if state else ""
        notes = state.notes if state else ""
        job_verifications = verifications.get(job.id, {})
        content_hash, snapshot = job_content_version(job, job_documents, positions_by_document)
        ocr_scores = [d.ocr_confidence for d in job_documents if d.ocr_confidence is not None]
        reference_date = job.application_deadline or job.application_start or today
        unread_documents = [d for d in job_documents if d.status in ("unavailable", "unreadable", "partially_read")]
        for position in decompose_job_positions(job, job_documents, positions_by_document):
            # Birincil kayıtta eksik olan tarih/şehir bilgisi diğer kaynaktaki kopyadan tamamlanır.
            for field in ("application_deadline", "application_start", "city"):
                if not position[field]:
                    position[field] = next((getattr(other, field) for other in duplicates if getattr(other, field)), None)
            position["reference_date"] = position["application_deadline"] or reference_date
            position["ocr"] = bool(ocr_scores)
            match = classify_public_job(position, profile)
            record = job_verifications.get(position["sub_id"]) or job_verifications.get("")
            effective = DECISION_CATEGORY[record.decision] if record else match["category"]
            counts[effective] += 1
            verification = None
            if record:
                stale = bool(record.content_hash) and record.content_hash != content_hash
                verification = {
                    "decision": record.decision,
                    "scope": "position" if record.position_id else "job",
                    "note": record.note,
                    "verified_at": record.verified_at.isoformat(timespec="minutes") if record.verified_at else None,
                    "stale": stale,
                    "changes": content_changes(record.content_snapshot, snapshot) if stale else [],
                }
            in_preference, out_of_preference = _preference_status(
                profile, preferred, position["city"] or "", job.organization, job.title,
            )
            status = "İptal Edildi" if cancelled else detect_application_status(
                position["application_start"], position["application_deadline"], today,
            )
            deadline = position["application_deadline"]
            item = {
                "id": position["sub_id"],
                "parent_job_id": job.id,
                "title": position["title"],
                "organization": position["organization"],
                "position": position["position"],
                "city": position["city"],
                "quota": position["quota"],
                "source_url": position["source_url"],
                "source_name": position["source_name"],
                "also_listed": also_listed,
                "announcement_date": _iso(job.announcement_date),
                "application_start": _iso(position["application_start"]),
                "application_deadline": _iso(deadline),
                "days_left": (deadline - today).days if deadline and status in ("Başvuru Açık", "Başvuru Başlamadı") else None,
                "application_status": status,
                "is_expired": status in ("Başvuru Sona Erdi", "İptal Edildi"),
                "recruitment_method": position["recruitment_method"] or "Kaynakta belirtilmedi",
                "employment_type": position["employment_type"] or "Kaynakta belirtilmedi",
                "education_requirement": (
                    position["education_requirement"] if position.get("position_specific")
                    else match["education"]["requirement"][:600] or position["education_requirement"]
                ),
                "qualification_codes": position["qualification_codes"] or ", ".join(match["qualification_codes"]),
                "kpss_score_type": position["kpss_score_type"] or "/".join(match["kpss"]["score_types"]),
                "kpss_min_score": position["kpss_min_score"] if position["kpss_min_score"] is not None else match["kpss"]["minimum_score"],
                "location_match": in_preference,
                "out_of_preference": out_of_preference,
                # Sistem kararı ile kullanıcının kararı ayrı tutulur; geçerli olan kullanıcının kararıdır.
                "system_category": match["category"],
                "category": effective,
                "verification": verification,
                "ocr_confidence": min(ocr_scores) if ocr_scores else None,
                "tracking": tracking,
                # Veri/belge durumu, uygunluk kategorisinden bağımsız gösterilir.
                "data_status": (
                    "ocr" if ocr_scores
                    else "listing_only" if match["data_quality"] == "listing_only"
                    else "partial" if unread_documents else "read"
                ),
                "review_required": (
                    (record is None and (match["category"] == "POTANSİYEL OLARAK UYGUN" or match["data_quality"] == "listing_only"))
                    or bool(job.cancellation_notice and not cancelled)
                    or bool(verification and verification["stale"])
                ),
                "cancellation_notice": job.cancellation_notice or "",
                "basis": position.get("basis"),
                "notes": notes,
                "first_seen": _iso(job.created_at),
                "written_exam_invite_text": position.get("written_exam_invite_text") or "",
                "written_exam_invite_count": position.get("written_exam_invite_count"),
                "match": {
                    "category": match["category"],
                    "reason": match["reason"],
                    "kind": match["kind"],
                    "data_quality": match["data_quality"],
                    "met_conditions": match["met_conditions"],
                    "failed_conditions": match["failed_conditions"],
                    "unknown_conditions": match["unknown_conditions"],
                    "general_conditions": match["general_conditions"],
                    "requirements": match["requirements"],
                    "education": match["education"] if full else {
                        key: value for key, value in match["education"].items() if key != "requirement"
                    },
                    "kpss": match["kpss"],
                },
            }
            if full:
                item["description"] = job.description or position["description"]
                item["document_review"] = review
            items.append(item)

    result = {
        "profile": profile,
        "counts": {"total": len(items), **counts, "education_count": len(opportunities)},
        "jobs": items,
        "education_opportunities": opportunities,
        "generated_at": today.isoformat(),
    }
    if cache_key is not None:
        if len(_CACHE) >= 4:
            _CACHE.clear()
        _CACHE[cache_key] = result
    return result


def job_summaries(matches: dict) -> list[dict]:
    """Pozisyon bazlı sonuçları ilan bazında özetler (bildirimler için)."""
    grouped: dict[int, dict] = {}
    for item in matches["jobs"]:
        summary = grouped.setdefault(item["parent_job_id"], {
            "job_id": item["parent_job_id"],
            "organization": item["organization"],
            "title": item["title"].split(" — ")[0],
            "source_name": item["source_name"],
            "application_deadline": item["application_deadline"],
            "application_status": item["application_status"],
            "days_left": item["days_left"],
            "tracking": item["tracking"],
            "location_match": item["location_match"],
            "category": item["category"],
            "data_quality": item["match"]["data_quality"],
            "kind": item["match"]["kind"],
            "verified": item["verification"] is not None,
            "stale": bool(item["verification"] and item["verification"]["stale"]),
            "stale_changes": (item["verification"] or {}).get("changes", []),
            "education_met": False,
            "positions": [],
        })
        if CATEGORY_ORDER[item["category"]] < CATEGORY_ORDER[summary["category"]]:
            summary["category"] = item["category"]
            summary["data_quality"] = item["match"]["data_quality"]
        if item["verification"] is not None:
            summary["verified"] = True
        if item["verification"] and item["verification"]["stale"]:
            summary["stale"], summary["stale_changes"] = True, item["verification"]["changes"]
        if item["match"]["education"]["status"] == "met" and item["category"] != "UYGUN DEĞİL":
            summary["education_met"] = True
        if item["location_match"]:
            summary["location_match"] = True
        if item["category"] != "UYGUN DEĞİL":
            summary["positions"].append(item["position"])
    return list(grouped.values())
