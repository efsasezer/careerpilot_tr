"""Kariyer Kapısı hesabından "Başvurularım", "İptal Edilen Başvurularım" ve "Sınav Bilgilerim" aktarımı.

Nasıl çalışır:
- Bu bilgisayarda GÖRÜNÜR bir tarayıcı penceresi açılır. e-Devlet girişini kullanıcı kendisi yapar;
  uygulama giriş formuna dokunmaz, şifreyi görmez, saklamaz. Güvenlik doğrulamaları aşılmaz.
- Giriş sonrası hesap menüsündeki bağlantılara tıklanır (adres tahmin edilmez) ve sayfalardaki
  tablolar okunur. Sitenin iç API'sine doğrudan istek atılmaz.
- Pencere kapanınca oturum da biter; çerez ya da oturum bilgisi diske yazılmaz.

Sınırlar: e-Devlet oturumu kısa sürdüğü ve şifre saklanmadığı için aktarım kendiliğinden
çalışamaz; her aktarımda kullanıcının giriş yapması gerekir. Hesap sayfalarının yapısı yalnızca
oturum açıkken görülebildiğinden, ilk gerçek aktarım yapılana kadar bu bölüm "doğrulanmadı"
olarak gösterilir.
"""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
import logging
import os
import re
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from .eligibility import normalize_text
from .models import AccountApplication, AppSetting, Job, UserJobState

logger = logging.getLogger(__name__)

START_URL = "https://kariyerkapisi.gov.tr/isealim"
SETTING_KEY = "kk_account"
SECTIONS = {
    "applications": ("basvurularim",),
    "cancelled": ("iptal edilen",),
    "exams": ("sinav bilgilerim", "sinav bilgileri"),
}
SECTION_LABELS = {"applications": "Başvurularım", "cancelled": "İptal Edilen Başvurularım", "exams": "Sınav Bilgilerim"}
LOGIN_WAIT_SECONDS = 300
# Sütun başlığı (sadeleştirilmiş) → alan. İlk eşleşen kazanır.
_COLUMNS = (
    ("organization", ("kurum", "kurulus")),
    ("title", ("ilan adi", "ilan basligi", "ilan", "pozisyon", "unvan", "kadro")),
    ("applied_date", ("basvuru tarihi", "basvuru zamani")),
    ("exam_date", ("sinav tarihi", "sinav zamani", "mulakat tarihi")),
    ("exam_place", ("sinav yeri", "sinav adresi", "sinav salonu", "yer")),
    ("result", ("sonuc", "puan", "basari durumu")),
    ("status", ("durum", "asama")),
)
_DATE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})")
_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")


def _parse_date(text: str) -> date | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def normalize_rows(section: str, headers: list[str], rows: list[list[str]]) -> list[dict]:
    """Sayfadan okunan tablo satırlarını alanlara çevirir."""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for index, header in enumerate(headers):
        name = normalize_text(header)
        for field, words in _COLUMNS:
            if field not in used and any(word in name for word in words):
                mapping[index] = field
                used.add(field)
                break
    records = []
    for cells in rows:
        cells = [" ".join((cell or "").split()) for cell in cells]
        if not any(cells):
            continue
        record = {"section": section, "raw": {headers[i] if i < len(headers) else f"Sütun {i + 1}": cell for i, cell in enumerate(cells) if cell}}
        for index, field in mapping.items():
            if index < len(cells):
                record[field] = cells[index]
        if not record.get("title") and not record.get("organization"):
            continue
        exam_text = record.get("exam_date", "")
        time_match = _TIME.search(exam_text)
        record["exam_time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2)}" if time_match else ""
        record["applied_date"] = _parse_date(record.get("applied_date", ""))
        record["exam_date"] = _parse_date(exam_text)
        records.append(record)
    return records


def fingerprint(record: dict) -> str:
    key = "|".join(normalize_text(str(record.get(field) or "")) for field in ("title", "organization", "applied_date", "exam_date"))
    return sha256(f"{record['section']}|{key}".encode("utf-8")).hexdigest()


def _stems(text: str) -> set[str]:
    return {word[:6] for word in re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).split() if len(word) >= 4}


def match_job(db: Session, record: dict) -> tuple[int | None, str]:
    """Hesaptaki kaydı ilan havuzundaki ilanla eşleştirir; emin değilse "needs_review"."""
    from .matching import _duplicate_groups
    from .sync import organization_key

    jobs = list(db.scalars(select(Job).where(Job.sector == "public", Job.archived_reason == "")).all())
    hidden, _ = _duplicate_groups(jobs)
    organization = organization_key(record.get("organization") or record.get("title") or "")
    wanted = _stems(f"{record.get('title', '')}")
    scored = []
    for job in jobs:
        if job.id in hidden:
            continue
        same_org = bool(organization) and organization_key(job.organization) == organization
        overlap = len(wanted & _stems(job.title)) / max(1, len(wanted))
        if not same_org and overlap < 0.75:
            continue
        applied = record.get("applied_date")
        in_window = bool(applied and job.application_deadline and (job.application_start or date.min) <= applied <= job.application_deadline)
        if applied and job.application_deadline and not in_window:
            continue  # başvuru tarihi bu ilanın başvuru dönemine uymuyor
        scored.append((2 * same_org + overlap + in_window, same_org and (in_window or overlap >= 0.6), job.id))
    if not scored:
        return None, "unmatched"
    scored.sort(reverse=True)
    best = scored[0]
    unique = len(scored) == 1 or scored[1][0] < best[0]
    return best[2], "matched" if best[1] and unique else "needs_review"


def store_records(db: Session, records: list[dict], now: datetime | None = None) -> dict:
    """Kayıtları ekler ya da günceller; aynı kayıt ikinci kez eklenmez."""
    from .matching import invalidate_cache

    now = now or datetime.now()
    report = {"new": 0, "updated": 0, "matched": 0, "needs_review": 0, "unmatched": 0}
    for record in records:
        key = fingerprint(record)
        row = db.scalar(select(AccountApplication).where(AccountApplication.section == record["section"], AccountApplication.fingerprint == key))
        if row is None:
            row = AccountApplication(section=record["section"], fingerprint=key, first_seen_at=now, last_seen_at=now)
            db.add(row)
            report["new"] += 1
        else:
            report["updated"] += 1
        row.title = (record.get("title") or "")[:500]
        row.organization = (record.get("organization") or "")[:300]
        row.status = (record.get("status") or "")[:200]
        row.result = (record.get("result") or "")[:300]
        row.applied_date, row.exam_date = record.get("applied_date"), record.get("exam_date")
        row.exam_time, row.exam_place = record.get("exam_time", ""), (record.get("exam_place") or "")[:500]
        row.raw = json.dumps(record.get("raw") or {}, ensure_ascii=False)
        row.last_seen_at = now
        if row.match_status != "confirmed":
            row.job_id, row.match_status = match_job(db, record)
        report[row.match_status if row.match_status in report else "matched"] += 1
        # Kesin eşleşen başvuru, ilan takibinde "Başvurdum" olarak işaretlenir (elle verilmiş ileri bir durum ezilmez).
        if row.section == "applications" and row.match_status in ("matched", "confirmed") and row.job_id:
            state = db.get(UserJobState, row.job_id)
            if state is None:
                db.add(UserJobState(job_id=row.job_id, tracking="applied", notes="", updated_at=now))
            elif state.tracking in ("", "saved"):
                state.tracking, state.updated_at = "applied", now
    db.commit()
    invalidate_cache()
    return report


# ---------------------------------------------------------------------------
# Tarayıcı
# ---------------------------------------------------------------------------

_TABLES_SCRIPT = """() => [...document.querySelectorAll('table')].map(table => ({
  headers: [...table.querySelectorAll('thead th')].map(cell => cell.innerText.trim()),
  rows: [...table.querySelectorAll('tbody tr')].map(row => [...row.querySelectorAll('td')].map(cell => cell.innerText.trim())),
})).filter(table => table.headers.length && table.rows.length)"""
_LINKS_SCRIPT = "() => [...document.querySelectorAll('a')].map(a => (a.innerText || a.title || '').trim()).filter(Boolean)"


def read_account(on_status=None, login_wait: int = LOGIN_WAIT_SECONDS) -> dict:
    """Görünür tarayıcıyı açar, kullanıcının girişini bekler ve üç bölümü okur."""
    from .kariyerkapisi import PlaywrightTimeoutError, _playwright_event_loop_policy, sync_playwright

    say = on_status or (lambda message: None)
    outcome: dict = {"records": [], "sections": {}, "menu": []}
    with _playwright_event_loop_policy(), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_context(locale="tr-TR").new_page()
            page.goto(START_URL, wait_until="domcontentloaded", timeout=45000)
            say("Açılan pencerede \"e-Devlet ile Giriş\" bağlantısından kendi bilgilerinle giriş yap. Şifren uygulamaya ulaşmaz.")
            try:
                page.wait_for_url(re.compile(r"kariyerkapisi\.gov\.tr/(?!isealim|elogin)[^?#]+", re.I), timeout=login_wait * 1000)
            except PlaywrightTimeoutError:
                outcome["error"] = "Giriş yapılmadı ya da süre doldu; hiçbir veri okunmadı."
                return outcome
            page.wait_for_load_state("networkidle", timeout=15000)
            outcome["menu"] = sorted(set(page.evaluate(_LINKS_SCRIPT)))[:80]
            for section, words in SECTIONS.items():
                say(f"{SECTION_LABELS[section]} okunuyor…")
                target = next((text for text in outcome["menu"] if any(word in normalize_text(text) for word in words)), None)
                if target is None:
                    outcome["sections"][section] = {"status": "not_found", "detail": "Hesap menüsünde bu bölümün bağlantısı bulunamadı."}
                    continue
                try:
                    page.get_by_role("link", name=target, exact=True).first.click(timeout=10000)
                    page.wait_for_load_state("networkidle", timeout=20000)
                    if "/isealim" in page.url:
                        outcome["error"] = "Oturum sona erdi; aktarım yarıda kaldı."
                        return outcome
                    records, headers, pages = [], [], 0
                    while pages < 20:
                        pages += 1
                        for table in page.evaluate(_TABLES_SCRIPT):
                            headers = table["headers"]
                            records.extend(normalize_rows(section, table["headers"], table["rows"]))
                        following = page.locator(".paginate_button.next:not(.disabled)").first
                        if not following.count():
                            break
                        following.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                    empty = "bulunamadi" in normalize_text(page.inner_text("body")[:20000]) or "kayit yok" in normalize_text(page.inner_text("body")[:20000])
                    status = "ok" if records else "empty" if empty or headers else "unreadable"
                    detail = "" if status != "unreadable" else "Sayfa açıldı ancak tablo bulunamadı; sayfa yapısı beklenenden farklı."
                    outcome["sections"][section] = {"status": status, "count": len(records), "columns": headers, "detail": detail}
                    outcome["records"].extend(records)
                except Exception as error:
                    outcome["sections"][section] = {"status": "error", "detail": f"Bölüm okunamadı ({type(error).__name__})."}
        finally:
            browser.close()
    return outcome


# ---------------------------------------------------------------------------
# Durum ve arka plan çalıştırma
# ---------------------------------------------------------------------------

def load_state(db: Session) -> dict:
    row = db.get(AppSetting, SETTING_KEY)
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


def _save_state(db: Session, state: dict) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        db.add(row)
    row.value = json.dumps(state, ensure_ascii=False)
    db.commit()


def can_open_browser() -> tuple[bool, str]:
    if os.getenv("RENDER") or os.getenv("CI"):
        return False, "Bu işlem yalnızca uygulama kendi bilgisayarında çalışırken yapılabilir; sunucuda tarayıcı penceresi açılamaz."
    return True, ""


class ImportManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = {"running": False, "message": ""}

    def start(self) -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "message": "Tarayıcı açılıyor…"}
        threading.Thread(target=self._run, name="careerpilot-kk-import", daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            run_import(on_status=lambda message: self.state.update(message=message))
        except Exception as error:  # pragma: no cover
            logger.exception("Kariyer Kapısı import failed")
            self.state["message"] = f"Aktarım başarısız: {type(error).__name__}"
        finally:
            self.state["running"] = False


import_manager = ImportManager()


def run_import(on_status=None) -> dict:
    from .database import SessionLocal

    outcome = read_account(on_status=on_status)
    with SessionLocal() as db:
        state = load_state(db)
        now = datetime.now().isoformat(timespec="seconds")
        summary = {"at": now, "sections": outcome["sections"], "error": outcome.get("error")}
        read_ok = [name for name, info in outcome["sections"].items() if info["status"] in ("ok", "empty")]
        if outcome["records"]:
            summary["stored"] = store_records(db, outcome["records"])
        if read_ok and not outcome.get("error"):
            state["last_success"] = now
            state["verified"] = state.get("verified") or bool(outcome["records"])
        if not read_ok and not outcome.get("error"):
            # Kişisel içerik değil, yalnızca menü başlıkları: yapı farkını teşhis etmek için.
            summary["menu"] = outcome["menu"]
        state["last_attempt"] = summary
        _save_state(db, state)
    if on_status:
        on_status(outcome.get("error") or "Aktarım tamamlandı.")
    return summary


def overview(db: Session) -> dict:
    state = load_state(db)
    rows = db.scalars(select(AccountApplication).order_by(AccountApplication.applied_date.desc().nullslast(), AccountApplication.id.desc())).all()
    jobs = {job.id: job for job in db.scalars(select(Job).where(Job.id.in_([row.job_id for row in rows if row.job_id]))).all()} if rows else {}
    allowed, reason = can_open_browser()
    return {
        "verified": bool(state.get("verified")),
        "last_success": state.get("last_success"),
        "last_attempt": state.get("last_attempt"),
        "running": import_manager.state["running"],
        "message": import_manager.state["message"],
        "can_import_here": allowed, "cannot_import_reason": reason,
        "items": [{
            "id": row.id, "section": row.section, "section_label": SECTION_LABELS[row.section], "title": row.title,
            "organization": row.organization, "status": row.status, "result": row.result,
            "applied_date": row.applied_date.isoformat() if row.applied_date else None,
            "exam_date": row.exam_date.isoformat() if row.exam_date else None, "exam_time": row.exam_time, "exam_place": row.exam_place,
            "job_id": row.job_id, "job_title": jobs[row.job_id].title if row.job_id in jobs else None,
            "match_status": row.match_status, "last_seen_at": row.last_seen_at.isoformat(timespec="seconds"),
        } for row in rows],
    }


if __name__ == "__main__":
    from .database import Base, engine
    from .migrate import migrate

    migrate()
    Base.metadata.create_all(bind=engine)
    print(json.dumps(run_import(on_status=print), ensure_ascii=False, indent=2, default=str))
