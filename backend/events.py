"""İlan metninden tarihli olayların (başvuru, sınav, sonuç, evrak) kural tabanlı çıkarımı.

Kurallar:
- Yalnızca metinde açıkça yazan tarih alınır; tarih yoksa olay üretilmez (uydurma yok).
- Her tarih, aynı cümledeki bağlama göre bir olaya bağlanır; mevzuat tarihleri, doğum tarihi
  koşulları ve sınav dönemleri gibi ilgisiz tarihler takvime girmez.
- Her olay için kanıt cümlesi saklanır. Kullanıcının düzenlediği/sildiği olaylar yeniden
  taramada ezilmez. Yapay zekâ modeli kullanılmaz.
"""

from __future__ import annotations

from . import clock
from datetime import date, datetime, timedelta
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .eligibility import _sentences, normalize_text, reflow_text
from .models import Job, JobDocument, JobEvent

EVENT_LABELS = {
    "application_start": "Başvuru başlıyor",
    "application_deadline": "Son başvuru günü",
    "exam": "Sınav",
    "interview": "Sözlü sınav / mülakat",
    "result": "Sonuç açıklanacak",
    "documents": "Evrak teslimi",
    "appointment": "Atama",
    "start_work": "Göreve başlama",
}
# Açık "etiket + tarih" kalıpları (ilan takvimi tabloları). Bir cümlede birden çok etiket olabilir;
# her etiket yalnızca hemen ardından gelen tarihe bağlanır.
_LABELLED = (
    ("interview", r"(?:sozlu sinav|mulakat|sozlu mulakat)\w*(?: yeri ve)? tarihi?"),
    ("exam", r"(?:giris sinavi|yazili sinav\w*|uygulamali sinav\w*|sinava? giris|sinav\w*)(?: yeri ve)? tarihi?"),
    ("exam", r"giris sinavi"),
    ("documents", r"(?:evrak|belge) teslim\w* (?:son )?tarihi?"),
    ("start_work", r"(?:goreve|ise) baslama tarihi?"),
)
_LABELLED_PATTERNS = [(kind, re.compile(pattern + r"(?: ve saati)?\s*[:\-–]?\s*")) for kind, pattern in _LABELLED]


def _labelled_dates(normalized: str) -> list[tuple[str, date, str]]:
    """("exam", tarih, saat) üçlüleri: etiketin hemen ardından (en çok 12 karakter sonra) gelen tarih."""
    dated = _dates(normalized)
    found: list[tuple[str, date, str]] = []
    taken: set[int] = set()
    for kind, pattern in _LABELLED_PATTERNS:
        for match in pattern.finditer(normalized):
            if kind == "exam" and ("sonuc" in normalized[max(0, match.start() - 4):match.end() + 8] or normalized[max(0, match.start() - 7):match.start()].strip().endswith(("sozlu", "mulakat"))):
                continue
            following = next(((value, start) for value, start in dated if match.end() <= start <= match.end() + 12), None)
            if following is None or following[1] in taken:
                continue
            taken.add(following[1])
            next_date = next((start for _, start in dated if start > following[1]), len(normalized))
            found.append((kind, following[0], _time(normalized[following[1]:min(next_date, following[1] + 40)])))
    return found
_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}
_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(20\d{2})(?!\d)")
_WORDED = re.compile(r"(?<!\d)(\d{1,2})\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\s+(20\d{2})(?!\d)")
_TIME = re.compile(r"saat\s*(\d{1,2})[.:](\d{2})|(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_URL = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:gov|edu|bel|org|com)\.tr(?:/[^\s,;)]*)?")
# Bu bağlamlardaki tarihler bir olayın tarihi değildir.
_IGNORED_CONTEXT = (
    "sayili", "resmi gazete", "dogmus", "dogumlu", "yasini", "yas sarti", "kanun", "yonetmelik",
    "itibariyla gecerli", "tarihinden once", "mezun ol", "kpss sonuc belgesi", "yilinda yapilan",
    "ucretini", "ucreti ", "ucretinin",  # sınav ücreti ödeme tarihleri sınav tarihi değildir
)


def _dates(normalized: str) -> list[tuple[date, int]]:
    found = []
    for match in _NUMERIC.finditer(normalized):
        value = _safe(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if value:
            found.append((value, match.start()))
    for match in _WORDED.finditer(normalized):
        value = _safe(int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)))
        if value:
            found.append((value, match.start()))
    return sorted(found, key=lambda item: item[1])


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _time(normalized: str) -> str:
    match = _TIME.search(normalized)
    if not match:
        return ""
    hour, minute = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    return f"{int(hour):02d}:{minute}" if int(hour) < 24 and int(minute) < 60 else ""


def _kind(normalized: str) -> str | None:
    has = lambda *words: any(word in normalized for word in words)  # noqa: E731
    if any(word in normalized for word in _IGNORED_CONTEXT):
        return None
    if has("hak kazanan", "cagrilacak aday", "sinava girecek aday") and has("ilan", "duyurul", "aciklan", "yayimlan", "web say", "internet"):
        return "result"
    if has("sonuc") and has("aciklan", "ilan edil", "duyurul", "yayimlan", "yayinlan", "ilan tarihi", "sonuclari ilan", "sonucu ilan", "sonuc tarihi", "sonuclari tarihi", "sonuc aciklama", "aciklanma"):
        return "result"
    if has("sozlu", "mulakat") and has("yapilacak", "tarih", "gerceklestiril", "alinacak"):
        return "interview"
    if has("sinav") and has("yapilacak", "sinav tarihi", "gerceklestiril", "tarihinde", "tarihleri arasinda") and not has("sonuc", "basvurular ", "basvuru tarih", "son basvuru", "basvuru sure", "basvurusu"):
        return "exam"
    if has("evrak", "belge teslim", "belgelerin teslim", "belgelerini teslim") and has("teslim"):
        return "documents"
    if has("atama") and has("yapilacak", "atamalar") and not has("basvuru"):
        return "appointment"
    return None


_RESULT_STAGES = (
    ("on degerlendirme", "Ön değerlendirme sonucu"), ("nihai", "Nihai sonuç"), ("yazili", "Yazılı sınav sonucu"),
    ("sozlu", "Sözlü sınav sonucu"), ("mulakat", "Mülakat sonucu"), ("giris sinav", "Giriş sınavı sonucu"),
    ("kura", "Kura sonucu"), ("basvuru sonuc", "Başvuru sonucu"),
)
_OTHER_LABEL = ("basvuru", "sinav tarihi", "sinavi tarihi", "baslangic", "bitis", "giris tarihi")


def _result_dates(normalized: str) -> list[tuple[date, str]]:
    """Cümledeki her "sonuç" ifadesine ait tarihi bulur: önce ifadeden hemen sonraki, yoksa hemen önceki tarih.

    Tablodan düzleşmiş metinlerde ("Son Başvuru Tarihi 20.11.2026 Sonuç İlan Tarihi 27.11.2026") araya başka
    bir tarih etiketi giriyorsa tarih o sonuca bağlanmaz; yanlış tarih yazmaktansa olay üretilmez.
    """
    dated = _dates(normalized)
    found: list[tuple[date, str]] = []
    for match in re.finditer(r"sonuc|hak kazanan", normalized):
        position = match.start()
        chosen = None
        after = next(((value, start) for value, start in dated if start > position), None)
        if match.group() == "hak kazanan":
            # "Sınava girmeye hak kazanan adaylar ... 09/12/2026 tarihinde ... ilan edilecektir."
            between = normalized[position:after[1]] if after else ""
            if after and (
                (after[1] - position <= 240 and "tarihinde" in normalized[after[1]:after[1] + 24])
                or (after[1] - position <= 70 and "ilan" in between)
            ):
                if after[0] not in [value for value, _ in found]:
                    found.append((after[0], "Sınava girmeye hak kazananlar"))
            continue
        if after and after[1] - position <= 110 and not any(label in normalized[position:after[1]] for label in _OTHER_LABEL):
            chosen = after[0]
        if chosen is None:
            before = next(((value, start) for value, start in reversed(dated) if start < position), None)
            if before and position - before[1] <= 60 and "tarih" in normalized[before[1]:position] \
                    and not any(label in normalized[before[1]:position] for label in _OTHER_LABEL):
                chosen = before[0]
        if chosen is None:
            continue
        context = normalized[max(0, position - 45):position + 12]
        label = next((name for word, name in _RESULT_STAGES if word in context), "")
        if (chosen, label) not in found and chosen not in [value for value, _ in found]:
            found.append((chosen, label))
    return found


def extract_events(text: str, *, today: date | None = None) -> list[dict]:
    """Metinden (kind, date, time, end_date, evidence, url) olayları çıkarır."""
    today = today or clock.today()
    earliest, latest = today - timedelta(days=120), today + timedelta(days=730)
    events: list[dict] = []
    seen: set[tuple] = set()
    for sentence in _sentences(reflow_text(text or "")):
        if len(sentence) > 700:
            continue
        normalized = normalize_text(sentence)
        evidence = " ".join(sentence.split())[:500]
        if not any(word in normalized for word in _IGNORED_CONTEXT):
            for labelled_kind, value, time_text in _labelled_dates(normalized):
                if earliest <= value <= latest and (labelled_kind, value) not in seen:
                    seen.add((labelled_kind, value))
                    events.append({
                        "kind": labelled_kind, "date": value, "end_date": None, "time": time_text, "title": "",
                        "evidence": evidence, "url": "", "method": "label", "confidence": "high",
                    })
        kind = _kind(normalized)
        if kind is None:
            continue
        if kind == "result":
            url = ""
            match = _URL.search(sentence.casefold())
            if match:
                url = match.group(0) if match.group(0).startswith("http") else f"https://{match.group(0)}"
            for value, label in _result_dates(normalized):
                if not earliest <= value <= latest or (kind, value) in seen:
                    continue
                seen.add((kind, value))
                events.append({
                    "kind": kind, "date": value, "end_date": None, "time": "", "title": label,
                    "evidence": evidence, "url": url[:1000],
                    "method": "label" if label else "sentence", "confidence": "high" if label else "medium",
                })
            continue
        if any(item["kind"] == kind and item["evidence"] == evidence and item["method"] == "label" for item in events):
            continue  # bu cümlede aynı tür için açık etiketli tarih bulundu; tahmine gerek yok
        dates = [value for value, _ in _dates(normalized) if earliest <= value <= latest]
        if not dates:
            continue
        start = dates[0]
        # Bitiş tarihi yalnızca cümle açıkça bir aralık veriyorsa ("... tarihleri arasında") alınır.
        is_range = len(dates) > 1 and "arasinda" in normalized and kind in ("exam", "interview", "documents")
        end = dates[1] if is_range and 0 < (dates[1] - start).days <= 14 else None
        key = (kind, start)
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "kind": kind, "date": start, "end_date": end, "time": _time(normalized), "title": "",
            "evidence": evidence, "url": "", "method": "sentence", "confidence": "medium",
        })
    return events


def _application_evidence(text: str, target: date) -> tuple[str, str]:
    """Başvuru tarihinin geçtiği cümleyi ve varsa saatini bulur."""
    for sentence in _sentences(reflow_text(text or "")):
        normalized = normalize_text(sentence)
        if not any(word in normalized for word in ("basvuru", "muracaat", "tercih")):
            continue
        dates = _dates(normalized)
        for index, (value, position) in enumerate(dates):
            if value != target:
                continue
            next_date = dates[index + 1][1] if index + 1 < len(dates) else len(normalized)
            return " ".join(sentence.split())[:500], _time(normalized[position:next_date])
    return "", ""


def sync_job_events(db: Session, job: Job, *, today: date | None = None) -> dict:
    """İlanın otomatik olaylarını günceller; kullanıcı düzenlemelerine dokunmaz."""
    documents = db.scalars(select(JobDocument).where(JobDocument.job_id == job.id)).all()
    readable = [doc.extracted_text for doc in documents if doc.extracted_text and doc.ocr_confidence is None and doc.status != "obsolete"]
    text = "\n".join(filter(None, [job.description or "", *[t for t in readable if t[:200] not in (job.description or "")]]))

    wanted: list[dict] = []
    for kind, value in (("application_start", job.application_start), ("application_deadline", job.application_deadline)):
        if value:
            evidence, time_text = _application_evidence(text, value)
            wanted.append({"kind": kind, "date": value, "end_date": None, "time": time_text,
                           "evidence": evidence or "Kaynağın ilan listesindeki başvuru tarihi.", "url": "", "title": "",
                           "method": "sentence" if evidence else "listing", "confidence": "high"})
    if job.status != "İptal edildi":
        wanted.extend(extract_events(text, today=today))

    existing = list(db.scalars(select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.source == "auto")).all())
    user_events = list(db.scalars(select(JobEvent).where(
        JobEvent.job_id == job.id, JobEvent.deleted.is_(False),
        ((JobEvent.source == "user") | JobEvent.user_edited.is_(True)),
    )).all())
    by_kind: dict[str, list[JobEvent]] = {}
    for event in existing:
        by_kind.setdefault(event.kind, []).append(event)
    now = clock.now()
    changed = created = 0
    kept: set[int] = set()
    for item in wanted:
        # A user-added or verified date is authoritative for that event kind.
        if any(event.kind == item["kind"] and event.user_edited for event in user_events):
            continue
        candidates = by_kind.get(item["kind"], [])
        same = next((event for event in candidates if event.event_date == item["date"]), None)
        if same is not None:
            kept.add(same.id)
            if not same.user_edited and not same.deleted:
                same.evidence, same.url = item["evidence"], item["url"] or same.url
                same.event_time, same.end_date = item["time"], item["end_date"]
                same.title = item.get("title", "") or same.title
                same.method, same.confidence = item.get("method", ""), item.get("confidence", "")
            continue
        # Aynı türde tek bir otomatik olay varsa ve tarihi değiştiyse: eski değer saklanır.
        movable = [event for event in candidates if event.id not in kept and not event.user_edited and not event.deleted]
        single = len([entry for entry in wanted if entry["kind"] == item["kind"]]) == 1 and len(movable) == 1
        if single:
            event = movable[0]
            kept.add(event.id)
            event.previous_date, event.event_date = event.event_date, item["date"]
            event.end_date, event.event_time = item["end_date"], item["time"]
            event.evidence, event.url, event.updated_at = item["evidence"], item["url"], now
            event.title = item.get("title", "")
            event.method, event.confidence = item.get("method", ""), item.get("confidence", "")
            changed += 1
            continue
        event = JobEvent(
            job_id=job.id, kind=item["kind"], event_date=item["date"], end_date=item["end_date"], event_time=item["time"],
            evidence=item["evidence"], url=item["url"], source="auto", updated_at=now, title=item.get("title", ""),
            method=item.get("method", ""), confidence=item.get("confidence", ""),
        )
        db.add(event)
        db.flush()
        kept.add(event.id)
        created += 1
    for event in existing:
        # Artık metinde bulunmayan otomatik olay kaldırılır; kullanıcının dokunduğu olay kalır.
        if event.id not in kept and not event.user_edited and not event.deleted:
            db.delete(event)
    return {"created": created, "changed": changed}


def refresh_all_events(db: Session) -> dict:
    totals = {"created": 0, "changed": 0}
    for job in db.scalars(select(Job).where(Job.sector == "public", Job.archived_reason == "")).all():
        result = sync_job_events(db, job)
        totals["created"] += result["created"]
        totals["changed"] += result["changed"]
    db.commit()
    return totals


# ---------------------------------------------------------------------------
# Kişisel görevler
# ---------------------------------------------------------------------------

def task_occurs_on(task, day: date) -> bool:
    if day < task.task_date or (task.until and day > task.until):
        return False
    if task.recurrence == "none":
        return day == task.task_date
    if task.recurrence == "daily":
        return True
    if task.recurrence == "weekly":
        return day.weekday() == task.task_date.weekday()
    if task.recurrence == "weekdays":
        days = {int(value) for value in (task.weekdays or "").split(",") if value.strip().isdigit()}
        return day.weekday() in days
    if task.recurrence == "monthly":
        return day.day == task.task_date.day
    return False


def task_occurrences(tasks, start: date, end: date) -> list[dict]:
    import json

    result = []
    for task in tasks:
        try:
            completed = set(json.loads(task.completed_dates or "[]"))
        except ValueError:
            completed = set()
        day = max(start, task.task_date)
        while day <= end:
            if task_occurs_on(task, day):
                result.append({
                    "task_id": task.id, "title": task.title, "description": task.description, "date": day.isoformat(),
                    "start_time": task.start_time, "end_time": task.end_time, "priority": task.priority,
                    "recurrence": task.recurrence, "done": day.isoformat() in completed,
                })
            day += timedelta(days=1)
    return sorted(result, key=lambda item: (item["date"], item["start_time"] or "99:99", item["title"]))
