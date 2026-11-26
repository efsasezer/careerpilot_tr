"""YLSY / "1416 Bursları" duyuruları (MEB Yükseköğretim ve Yurt Dışı Eğitim Genel Müdürlüğü).

Tek resmî kaynak yyegm.meb.gov.tr'dir. Duyurular sitenin herkese açık RSS akışından izlenir; her
duyurunun ayrıntı sayfası ve ekleri okunur. Başvuru kılavuzu ve tercih tabloları yayımlandığında
şartlar (ALES, not ortalaması, doğum yılı, başvuru tarihleri) kılavuzdaki cümlelerle birlikte
çıkarılır. Kılavuzda bulunamayan şart uydurulmaz; "okunamadı" olarak kalır.
"""

from __future__ import annotations

from . import clock
from datetime import date, datetime
from email.utils import parsedate_to_datetime
import html as html_lib
import io
import json
import logging
import re
import time
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import tls
from .eligibility import normalize_text
from .models import Announcement
from .sources.base import DEFAULT_HEADERS, parse_html_page

logger = logging.getLogger(__name__)

TOPIC = "ylsy"
SITE = "https://yyegm.meb.gov.tr"
RSS_URL = f"{SITE}/meb_iys_dosyalar/xml/rss_duyurular.xml"
SOURCE_NAME = "MEB Yükseköğretim ve Yurt Dışı Eğitim Genel Müdürlüğü"
# RSS yalnızca son duyuruları içerir. İlk kurulumda son dönemin (2025 Yılı 1416 Bursları) resmî
# duyuru sayfaları da bir kez okunur; bunlar "geçmiş duyuru" olarak eklenir ve bildirim üretmez.
BACKFILL_IDS = (1094, 1108, 1109, 1110, 1137, 1149, 1157, 1168, 1171, 1177, 1182, 1183)
CATEGORY_LABELS = {
    "guide": "Başvuru kılavuzu", "application": "Başvuru", "interview": "Sözlü sınav / mülakat",
    "result": "Sonuç", "placement": "Tercih / yerleştirme", "documents": "Belge teslimi",
    "language": "Dil kursu", "other": "Duyuru",
}
ALES_TYPE_CODES = {"sayisal": "SAY", "sozel": "SÖZ", "esit_agirlik": "EA"}
_MONTHS = ("ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik")


def is_relevant(title: str) -> bool:
    text = normalize_text(title)
    return "ylsy" in text or "1416" in text or ("yurt disi" in text and "lisansustu" in text)


def categorize(title: str) -> str:
    text = normalize_text(title)
    if "dil kurs" in text or "dil tercih" in text:
        return "language"
    if "kilavuz" in text:
        return "guide"
    if "belge teslim" in text:
        return "documents"
    if "giris belge" in text or ("cagril" in text and "sonuc" not in text):
        return "interview"
    if "sonuc" in text or "hak kazanan" in text:
        return "result"
    if "tercih" in text or "yerlestirme" in text:
        return "placement"
    if "sozlu" in text or "mulakat" in text or "giris belge" in text:
        return "interview"
    if "basvuru" in text:
        return "application"
    return "other"


def cycle_year(title: str) -> int | None:
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", title)
    return int(match.group(1)) if match else None


def _get(url: str) -> bytes:
    response = tls.get(url, headers=DEFAULT_HEADERS, timeout=(8, 60))
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {url}")
    return response.content


def parse_rss(body: bytes) -> list[dict]:
    items = []
    for node in ET.fromstring(body).iter("item"):
        title = html_lib.unescape((node.findtext("title") or "").strip())
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = None
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "").date()
        except (TypeError, ValueError):
            pass
        items.append({"title": title, "url": link, "date": published})
    return items


def parse_detail(url: str, html: str) -> dict:
    """Duyuru sayfasından başlık, yayın tarihi, metin ve ek belgeleri okur."""
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = html_lib.unescape(" ".join((title_match.group(1) if title_match else "").split()))
    title = re.split(r"\s+[|\-–]\s+(?:T\.?C\.?|Millî|Milli|Yükseköğretim ve Yurt)", title)[0].strip()
    published = None
    match = re.search(r"Yay[ıi]n\s*:\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})", html)
    if match:
        published = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    start = html.find("article-detay")
    body = html[start:] if start >= 0 else html
    links, text = parse_html_page(f"<div class=\"{body}" if start >= 0 else body)
    attachments = []
    for link in links:
        href = link["href"].strip()
        if "/meb_iys_dosyalar/" in href and href.casefold().endswith((".pdf", ".xlsx", ".xls", ".docx", ".doc")):
            item = {"title": " ".join(link["text"].split())[:200] or "Ek belge", "url": urljoin(url, href)}
            if item["url"] not in [entry["url"] for entry in attachments]:
                attachments.append(item)
    cut = text.find("Paylaş")
    return {"title": title, "date": published, "text": (text if cut < 200 else text[:cut])[:6000], "attachments": attachments[:20]}


# ---------------------------------------------------------------------------
# Kılavuz ve tercih tabloları
# ---------------------------------------------------------------------------

def _pdf_pages(body: bytes):
    import pdfplumber

    return pdfplumber.open(io.BytesIO(body))


def _sentence(text: str, pattern: str) -> tuple[re.Match | None, str]:
    flat = " ".join(text.split())
    match = re.search(pattern, flat, re.I)
    if not match:
        return None, ""
    start = max(flat.rfind(". ", 0, match.start()) + 2, match.start() - 300)
    end = flat.find(".", match.end())
    return match, flat[start:(end + 1 if 0 < end - match.end() < 300 else match.end() + 200)].strip()


def parse_guide_text(text: str) -> dict:
    """Kılavuz metninden şartları, kanıt cümlesiyle birlikte çıkarır. Bulunamayan alan eklenmez."""
    facts: dict = {}
    match, evidence = _sentence(text, r"ALES puan türünden en az (\d{2,3})")
    if match:
        facts["ales_min"] = {"value": float(match.group(1)), "evidence": evidence}
    match, evidence = _sentence(text, r"Başvurularda ((?:20\d{2}[ ,]*(?:ve )?)+)yıllarında yapılan Akademik Personel")
    if match:
        facts["ales_years"] = {"value": [int(year) for year in re.findall(r"20\d{2}", match.group(1))], "evidence": evidence}
    match, evidence = _sentence(text, r"4 üzerinden en az (\d)[.,](\d{1,2})")
    if match:
        facts["gpa_min"] = {"value": float(f"{match.group(1)}.{match.group(2)}"), "evidence": evidence}
    match, evidence = _sentence(text, r"için (\d{4}) ve daha sonraki yıllarda,? [“\"']?Sadece Doktora[”\"']? yazılı alanlar için (\d{4}) ve daha sonraki")
    if match:
        facts["birth_year_min"] = {"value": {"master": int(match.group(1)), "phd": int(match.group(2))}, "evidence": evidence}
    match, evidence = _sentence(text, r"başvurularını (\d{1,2})\s*-\s*(\d{1,2}) (\w+) (20\d{2}) tarihleri arasında")
    if match and normalize_text(match.group(3)) in _MONTHS:
        month = _MONTHS.index(normalize_text(match.group(3))) + 1
        year = int(match.group(4))
        try:
            facts["application"] = {
                "start": date(year, month, int(match.group(1))).isoformat(),
                "end": date(year, month, int(match.group(2))).isoformat(), "evidence": evidence,
            }
        except ValueError:
            pass
    for key, pattern in (
        ("citizenship", r"Türkiye Cumhuriyeti vatandaşı olmak"),
        ("degree_only", r"Başvurular yalnızca lisans mezuniyetiyle yapılır"),
        ("discipline", r"kınama cezasından daha ağır bir disiplin cezası almamış olmak"),
        ("military", r"Erkek adaylar için askerlikle ilişiği bulunmamak"),
        ("health", r"Sağlık durumu yurt dışında öğrenim görmeye"),
        ("language", r"puan eşitliği halinde yabancı dil puanı"),
    ):
        match, evidence = _sentence(text, pattern)
        if match:
            facts[key] = {"evidence": evidence}
    return facts


def parse_quota_table(body: bytes) -> list[dict]:
    """Tercih tablosunu (Tablo 1/2) satır satır okur; sütunlar başlık adından bulunur."""
    rows: list[dict] = []
    with _pdf_pages(body) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header = [normalize_text(cell or "").replace("\n", " ") for cell in table[0]]

                def column(*words):
                    return next((i for i, name in enumerate(header) if all(word in " ".join(name.split()) for word in words)), None)

                codes_col, ales_col = column("lisans mezuniyet kod"), column("ales")
                if codes_col is None or ales_col is None:
                    continue
                columns = {
                    "group": column("ogrenim gruplari"), "institution": column("adina ogrenim") if column("adina ogrenim") is not None else 3,
                    "field": column("ogrenim gorulecek alanlar"), "quota": column("kurum bazli"),
                    "level": column("ogrenim seviyesi"), "countries": column("ulkeler"),
                }
                for cells in table[1:]:
                    if len(cells) != len(header) or not cells[0] or not re.fullmatch(r"\d{6,8}", (cells[0] or "").strip()):
                        continue

                    def value(name):
                        index = columns[name]
                        return " ".join((cells[index] or "").split()) if index is not None else ""

                    codes = re.sub(r"\s+", "", cells[codes_col] or "")
                    rows.append({
                        "group_code": cells[0].strip(), "area_code": (cells[1] or "").strip(), "group": value("group"),
                        "institution": value("institution"), "field": value("field"), "quota": value("quota"),
                        "ales_types": [part for part in re.sub(r"\s+", "", cells[ales_col] or "").split("/") if part],
                        "codes": [code for code in codes.split(",") if re.fullmatch(r"\d{4}", code)],
                        "level": value("level"), "countries": value("countries"),
                    })
    return rows


def parse_code_table(body: bytes) -> dict[str, str]:
    """Tablo 3: lisans mezuniyet alan kodu → alan adı."""
    codes: dict[str, str] = {}
    with _pdf_pages(body) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table or []:
                    cells = [" ".join((cell or "").split()) for cell in cells]
                    for index, cell in enumerate(cells[:-1]):
                        if re.fullmatch(r"\d{4}", cell) and cells[index + 1] and not cells[index + 1].isdigit():
                            codes[cell] = cells[index + 1]
    return codes


def read_guide(attachments: list[dict], fetch=_get) -> dict:
    """Kılavuz duyurusunun eklerinden şartları ve tercih tablolarını okur."""
    facts: dict = {"tables": [], "codes": {}, "errors": []}
    for attachment in attachments:
        name = normalize_text(f"{attachment['title']} {attachment['url']}")
        if not attachment["url"].casefold().endswith(".pdf"):
            continue
        try:
            if "tablo3" in name.replace(" ", "") or "lisans alan kod" in name or "alankodlari" in name:
                facts["codes"].update(parse_code_table(fetch(attachment["url"])))
            elif ("tablo1" in name.replace(" ", "") or "tablo2" in name.replace(" ", "")) and "eklenen" not in name:
                for row in parse_quota_table(fetch(attachment["url"])):
                    facts["tables"].append({**row, "document": attachment["url"]})
            elif "kilavuz" in name and "tablo" not in name:
                with _pdf_pages(fetch(attachment["url"])) as pdf:
                    text = "\n".join((page.extract_text() or "") for page in pdf.pages)
                facts.update(parse_guide_text(text))
                facts["guide_url"] = attachment["url"]
        except Exception as error:
            facts["errors"].append(f"{attachment['title']}: okunamadı ({type(error).__name__})")
        time.sleep(1)
    return facts


# ---------------------------------------------------------------------------
# Senkronizasyon
# ---------------------------------------------------------------------------

def _store(db: Session, url: str, fallback_title: str, fallback_date: date | None, *, backfill: bool, fetch) -> Announcement | None:
    detail = {"title": fallback_title, "date": fallback_date, "text": "", "attachments": []}
    if "/icerik/" in url:
        html = fetch(url).decode("utf-8", "replace")
        parsed = parse_detail(url, html)
        detail.update({key: value for key, value in parsed.items() if value})
    elif url.casefold().endswith(".pdf"):
        detail["attachments"] = [{"title": fallback_title, "url": url}]
    title = detail["title"] or fallback_title
    if not title or not is_relevant(title):
        return None
    category = categorize(title)
    facts: dict = {"cycle": cycle_year(title), "backfill": backfill}
    if category == "guide" and "tablo" not in normalize_text(title).split("kilavuz", 1)[-1][:30]:
        facts.update(read_guide(detail["attachments"], fetch))
    row = Announcement(
        topic=TOPIC, url=url[:1200], title=title[:500], category=category, published_date=detail["date"],
        source=SOURCE_NAME, summary=detail["text"], attachments=json.dumps(detail["attachments"], ensure_ascii=False),
        facts=json.dumps(facts, ensure_ascii=False), first_seen_at=clock.now(),
    )
    db.add(row)
    db.commit()
    return row


def sync_ylsy(db: Session, fetch=_get) -> dict:
    """Resmî duyuru akışını kontrol eder; yeni YLSY/1416 duyurularını ekler. Aynı duyuru iki kez eklenmez."""
    from .models import AppSetting

    report = {"status": "ok", "new": 0, "checked_at": clock.now().isoformat(timespec="seconds"), "error": None}
    known = set(db.scalars(select(Announcement.url).where(Announcement.topic == TOPIC)).all())
    first_run = not known  # ilk kurulumda bulunan eski duyurular bildirim üretmez
    try:
        if not known:
            for identifier in BACKFILL_IDS:
                url = f"{SITE}/www/x/icerik/{identifier}"
                try:
                    if _store(db, url, "", None, backfill=True, fetch=fetch) is not None:
                        known.add(url)
                except Exception:
                    db.rollback()
                    logger.warning("YLSY backfill page %s could not be read", identifier)
                time.sleep(1)
        items = parse_rss(fetch(RSS_URL))
        if not items:
            raise RuntimeError("Duyuru akışı boş döndü; kaynak yapısı değişmiş olabilir.")
        known_ids = {match.group(1) for url in known if (match := re.search(r"/icerik/(\d+)", url))}
        for item in items:
            identifier = re.search(r"/icerik/(\d+)", item["url"])
            if not is_relevant(item["title"]) or item["url"] in known or (identifier and identifier.group(1) in known_ids):
                continue
            if _store(db, item["url"], item["title"], item["date"], backfill=first_run, fetch=fetch) is not None:
                known.add(item["url"])
                report["new"] += 1
            time.sleep(1)
    except Exception as error:
        db.rollback()
        report.update(status="error", error=f"MEB duyuru kaynağı okunamadı: {str(error)[:200]}")
    setting = db.get(AppSetting, "ylsy_sync")
    if setting is None:
        setting = AppSetting(key="ylsy_sync")
        db.add(setting)
    previous = {}
    try:
        previous = json.loads(setting.value or "{}")
    except ValueError:
        pass
    report["last_success"] = report["checked_at"] if report["status"] == "ok" else previous.get("last_success")
    setting.value = json.dumps(report, ensure_ascii=False)
    db.commit()
    return report


# ---------------------------------------------------------------------------
# Adayın şartları
# ---------------------------------------------------------------------------

def _load(row: Announcement, field: str, default):
    try:
        value = json.loads(getattr(row, field) or "")
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def candidate_codes(codes: dict[str, str], department: str, aliases: str = "") -> list[str]:
    names = {normalize_text(name).strip() for name in [department, *aliases.split(",")] if name.strip()}
    return sorted(code for code, name in codes.items() if normalize_text(name).strip() in names)


def assess(profile, guide: Announcement | None, today: date | None = None) -> dict:
    """Adayın en son yayımlanan kılavuza göre durumu. Puan türü doğrulanmadan karar verilmez."""
    today = today or clock.today()
    if guide is None:
        return {"available": False, "message": "Resmî başvuru kılavuzu henüz okunamadı; şartlar kılavuz okunduğunda gösterilecek."}
    facts = _load(guide, "facts", {})
    cycle = facts.get("cycle")
    checks: list[dict] = []

    def add(name: str, status: str, detail: str, key: str | None = None) -> None:
        checks.append({"name": name, "status": status, "detail": detail, "evidence": (facts.get(key) or {}).get("evidence", "") if key else ""})

    score = getattr(profile, "ales_score", None)
    score_type = getattr(profile, "ales_score_type", "") or ""
    minimum = (facts.get("ales_min") or {}).get("value")
    if minimum is None:
        add("ALES puanı", "unknown", "En az puan kılavuzdan okunamadı; kılavuzdan kontrol et.")
    elif score is None:
        add("ALES puanı", "unknown", f"Kılavuz en az {minimum:g} istiyor; profilinde ALES puanı yok.", "ales_min")
    else:
        add("ALES puanı", "met" if score >= minimum else "not_met",
            f"Puanın {score:g}; kılavuz ilgili puan türünde en az {minimum:g} istiyor.", "ales_min")
    if not score_type:
        add("ALES puan türü", "unknown",
            "Puanının hangi türde (Sayısal, Sözel, Eşit Ağırlık) olduğu profilinde yazmıyor. Her alan kendi puan türünü ister; "
            "türü doğrulamadan uygunluk kararı verilmez. Profilden ALES puan türünü seç.")
    else:
        add("ALES puan türü", "met", f"Profilindeki puan türü: {ALES_TYPE_CODES[score_type]}. Alan bazında aşağıda karşılaştırıldı.")
    years = (facts.get("ales_years") or {}).get("value") or []
    ales_year = getattr(profile, "ales_year", None)
    if years:
        if ales_year is None:
            add("ALES geçerlilik yılı", "unknown", f"Geçerli sınav yılları: {', '.join(map(str, years))}. Sınava girdiğin yılı profiline ekle.", "ales_years")
        else:
            add("ALES geçerlilik yılı", "met" if ales_year in years else "not_met",
                f"Sınav yılın {ales_year}; geçerli yıllar: {', '.join(map(str, years))}.", "ales_years")
    gpa_min = (facts.get("gpa_min") or {}).get("value")
    gpa = getattr(profile, "gpa", None)
    if gpa_min is not None:
        if gpa is None:
            add("Lisans not ortalaması", "unknown", f"4 üzerinden en az {gpa_min:g} isteniyor; profilinde not ortalaması yok.", "gpa_min")
        else:
            add("Lisans not ortalaması", "met" if gpa >= gpa_min else "not_met", f"Ortalaman {gpa:g}; en az {gpa_min:g} isteniyor.", "gpa_min")
    birth = (facts.get("birth_year_min") or {}).get("value") or {}
    birth_date = getattr(profile, "birth_date", None)
    if birth:
        if birth_date is None:
            add("Doğum yılı", "unknown",
                f"Yüksek lisans içeren alanlar için {birth['master']}, yalnızca doktora alanları için {birth['phd']} ve sonrası doğumlu olmak gerekiyor; profilinde doğum tarihi yok.",
                "birth_year_min")
        else:
            status = "met" if birth_date.year >= birth["master"] else "partial" if birth_date.year >= birth["phd"] else "not_met"
            add("Doğum yılı", "met" if status == "met" else "unknown" if status == "partial" else "not_met",
                f"Doğum yılın {birth_date.year}. Yüksek lisans içeren alanlar: {birth['master']} ve sonrası; yalnızca doktora: {birth['phd']} ve sonrası.",
                "birth_year_min")
    for key, name in (("citizenship", "T.C. vatandaşlığı"), ("degree_only", "Lisans mezuniyetiyle başvuru"), ("discipline", "Disiplin cezası"),
                      ("military", "Askerlik"), ("health", "Sağlık durumu"), ("language", "Yabancı dil")):
        if key in facts:
            add(name, "info", "Kılavuzdaki koşul; kendin doğrula." if key != "language" else "Başvuru için dil puanı şartı yok; puan eşitliğinde öncelik sağlar.", key)

    codes = candidate_codes(facts.get("codes") or {}, getattr(profile, "department", "") or "", getattr(profile, "department_aliases", "") or "")
    candidate_type = ALES_TYPE_CODES.get(score_type)
    fields = []
    for row in facts.get("tables") or []:
        if not set(codes) & set(row["codes"]):
            continue
        phd_only = "sadece doktora" in normalize_text(row["level"])
        if not candidate_type:
            type_status = "unknown"
        else:
            type_status = "met" if candidate_type in row["ales_types"] else "not_met"
        age_status = "unknown"
        if birth and birth_date:
            age_status = "met" if birth_date.year >= (birth["phd"] if phd_only else birth["master"]) else "not_met"
        fields.append({**{key: row[key] for key in ("group_code", "area_code", "group", "institution", "field", "quota", "level", "countries", "document")},
                       "ales_types": row["ales_types"], "ales_type_status": type_status, "age_status": age_status})
    hard = [check["status"] for check in checks if check["status"] != "info"]
    if not fields:
        decision = "no_fields"
        message = ("Kılavuzun tercih tablolarında bölümünün kodu bulunamadı." if not codes
                   else "Bölümünün kabul edildiği bir alan bulunamadı.")
        if not (facts.get("tables") and facts.get("codes")):
            message = "Tercih tabloları okunamadı; alanları resmî tablolardan kontrol et."
    elif "not_met" in hard:
        decision, message = "not_eligible", "En az bir genel şartı karşılamıyorsun; ayrıntı aşağıda."
    elif "unknown" in hard:
        decision = "needs_verification"
        message = "Uygunluk kararı verilmedi: aşağıdaki eksik bilgiler doğrulanmalı. Listelenen alanlar bölümünün kabul edildiği alanlardır."
    else:
        usable = [field for field in fields if field["ales_type_status"] == "met" and field["age_status"] != "not_met"]
        decision = "eligible" if usable else "not_eligible"
        message = f"Genel şartları karşılıyorsun; {len(usable)} alana başvurabilirsin." if usable else "Puan türün ya da doğum yılın bölümünün kabul edildiği alanlarla uyuşmuyor."
    return {
        "available": True, "cycle": cycle, "guide_title": guide.title, "guide_url": guide.url, "guide_pdf": facts.get("guide_url"),
        "guide_date": guide.published_date.isoformat() if guide.published_date else None,
        "decision": decision, "message": message, "checks": checks, "department_codes": codes,
        "fields": fields, "application": facts.get("application"), "read_errors": facts.get("errors") or [],
    }


def announcement_payload(row: Announcement) -> dict:
    facts = _load(row, "facts", {})
    return {
        "id": row.id, "title": row.title, "url": row.url, "category": row.category,
        "category_label": CATEGORY_LABELS.get(row.category, "Duyuru"),
        "published_date": row.published_date.isoformat() if row.published_date else None,
        "first_seen_at": row.first_seen_at.isoformat(timespec="seconds"), "cycle": facts.get("cycle"),
        "summary": (row.summary or "")[:700], "attachments": _load(row, "attachments", []), "backfill": bool(facts.get("backfill")),
    }


def overview(db: Session, profile, today: date | None = None) -> dict:
    from .models import AppSetting

    today = today or clock.today()
    rows = db.scalars(select(Announcement).where(Announcement.topic == TOPIC)).all()
    rows = sorted(rows, key=lambda row: (row.published_date or row.first_seen_at.date(), row.id), reverse=True)
    guides = [row for row in rows if row.category == "guide" and _load(row, "facts", {}).get("ales_min")]
    guide = guides[0] if guides else None
    cycles = sorted({_load(row, "facts", {}).get("cycle") for row in rows} - {None}, reverse=True)
    setting = db.get(AppSetting, "ylsy_sync")
    try:
        sync = json.loads(setting.value) if setting and setting.value else None
    except ValueError:
        sync = None
    current_announced = today.year in cycles
    if current_announced:
        notice = f"{today.year} dönemi duyurulmuş; duyurular aşağıda."
    elif cycles:
        notice = (f"{today.year} YLSY / 1416 Bursları için resmî duyuru henüz yayımlanmadı. En son dönem {cycles[0]}. "
                  "Aşağıdaki şartlar o dönemin kılavuzuna göredir; yeni kılavuz yayımlandığında bildirim alacaksın ve şartlar yeniden kontrol edilecek.")
    else:
        notice = "Henüz duyuru okunamadı."
    return {
        "source": {"name": SOURCE_NAME, "url": f"{SITE}/www/duyurular/kategori/2"},
        "sync": sync, "notice": notice, "latest_cycle": cycles[0] if cycles else None, "current_year_announced": current_announced,
        "announcements": [announcement_payload(row) for row in rows],
        "assessment": assess(profile, guide, today),
    }
