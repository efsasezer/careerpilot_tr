"""Sonuç duyurusu takibi.

Başvurusu biten her ilan için kurumun resmî sitesi (ilan metninde yazan adres) düzenli olarak
kontrol edilir; sonuç duyuruları bulunur ve doğru ilanla eşleştirilir.

İlkeler:
- Yalnızca kurumun kendi sitesine bakılır; adres ilan metninden ya da kullanıcıdan gelir.
- robots.txt'e uyulur, istekler seyrek atılır, erişim engeli aşılmaya çalışılmaz.
- Site okunamadıysa "sonuç yok" denmez; durum "kontrol edilemedi" olarak kaydedilir.
- Eşleşme kesin değilse duyuru "Eşleşme doğrulanmalı" olarak saklanır.
- Sonuç listelerindeki kişi adları saklanmaz; yalnızca başlık, tarih ve bağlantı tutulur.
"""

from __future__ import annotations

from . import clock
from datetime import date, datetime, timedelta
import json
import logging
import re
import time
from urllib import robotparser
from urllib.parse import urldefrag, urlsplit

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, tls
from .eligibility import _sentences, is_academic_listing, normalize_text, reflow_text
from .models import DocumentPosition, Job, JobDocument, JobEvent, ResultAnnouncement, ResultTracking, UserJobState
from .sources.base import DEFAULT_HEADERS, USER_AGENT, absolute_url, parse_html_page

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "application": "Başvuru / ön değerlendirme sonucu",
    "exam": "Yazılı sınav sonucu",
    "interview": "Sözlü sınav / mülakat sonucu",
    "final": "Nihai sonuç",
    "list": "Asil / yedek liste",
    "placement": "Yerleştirme / atama sonucu",
    "result": "Sonuç duyurusu",
}
FINAL_KINDS = {"final", "list", "placement"}
TRACK_DAYS = 300  # son başvurudan sonra bu kadar gün izlenir
MAX_PAGES_PER_SITE = 6
MAX_DETAILS_PER_JOB = 6

_HOST = re.compile(
    r"(?:https?://)?((?:[a-z0-9-]+\.)+(?:gov|edu|bel|org|com|k12|pol|tsk|av|bbs|net)\.tr)(/[^\s,;)\"'<>]*)?", re.I
)
# Kurumun kendi sitesi sayılmayan ortak platformlar.
_SHARED_HOSTS = (
    "kariyerkapisi", "cbiko.gov.tr", "turkiye.gov.tr", "osym.gov.tr", "sbb.gov.tr", "resmigazete.gov.tr",
    "ilan.gov.tr", "iskur.gov.tr", "mevzuat.gov.tr", "csb.gov.tr", "yok.gov.tr", "yokatlas", "meb.gov.tr/meb_iys",
    "e-devlet", "edevlet", "ptt.gov.tr", "nvi.gov.tr", "uyap.gov.tr", "sgk.gov.tr", "kvkk.gov.tr", "basin-ilan",
)
_RESULT_WORDS = ("sonuc", "kazanan", "basari liste", "basari sira", "yerlestirme", "hak kazan", "asil ve yedek", "asil yedek", "asil aday", "yedek aday", "asil liste", "yedek liste")
# Personel alımıyla ilgisi olmayan "sonuç" duyuruları.
_UNRELATED = (
    "ogrenci", "yatay gecis", "dikey gecis", "burs", "lisansustu", "yuksek lisans", "doktora", "ihale", "erasmus", "farabi",
    "mevlana", "yaz okulu", "cift anadal", "yandal", "muafiyet", "formasyon", "ozel yetenek", "kiralama", "satis", "tez ",
    "yurt basvuru", "bap ", "proje pazari", "yarisma", "turnuva", "secim sonuc", "anket", "odul", "tubitak 22", "hazirlik sinif",
    "yeterlik sinav", "butunleme", "final sinav", "ara sinav", "mazeret", "kurs", "sertifika", "staj", "kayit hakki", "ek kontenjan",
    "akademik tesvik", "tesvik", "kura cekimi sonucu hak sahipleri", "konut", "dogrudan temin", "yokdil", "ales sonuc", "kpss sonuc",
)
_INDEX_HINTS = ("duyuru", "ilan", "haber", "personel", "sonuc", "sinav", "insan-kaynak", "insan kaynak", "kariyer", "tum", "arsiv")
_GENERIC = {
    "alim", "alimi", "ilan", "ilani", "duyuru", "duyurusu", "sonuc", "sonuclari", "hakkinda", "icin", "ile", "yili", "kamu",
    "edilecek", "alinacak", "baskanligi", "baskanligindan", "mudurlugu", "mudurlugunden", "rektorlugu", "rektorlugunden",
    "universitesi", "belediye", "belediyesi", "bakanligi", "bakanligindan", "genel", "kurumu", "ilişkin", "iliskin", "olarak",
    "yapilacak", "sinav", "sinavi", "giris", "personel", "personeli", "aday", "adaylar", "liste", "listesi", "tarihli",
}
# Aynı kurumun farklı alımlarını ayırt eden kadro grupları.
_ROLE_GROUPS = {
    "ogretim-uyesi": ("ogretim uyesi", "dr ogr", "docent", "profesor"),
    "ogretim-gorevlisi": ("ogretim gorevlisi",),
    "arastirma-gorevlisi": ("arastirma gorevlisi",),
    "ogretim-elemani": ("ogretim elemani", "akademik personel"),
    "sozlesmeli-bilisim": ("bilisim personeli", "sozlesmeli bilisim"),
    "sozlesmeli": ("sozlesmeli personel", "4/b", "4 b", "sozlesmeli"),
    "isci": ("surekli isci", "isci alim", "isci"),
    "zabita": ("zabita",),
    "itfaiye": ("itfaiye",),
    "uzman-yardimcisi": ("uzman yardimci", "mufettis yardimci", "denetci yardimci", "denetmen yardimci", "kontrolor"),
    "memur": ("memur",),
    "koruma": ("koruma ve guvenlik", "guvenlik gorevlisi", "ozel guvenlik"),
    "saglik": ("hemsire", "saglik personeli", "ebe ", "eczaci", "hekim", "doktor"),
    "muhendis": ("muhendis",),
    "avukat": ("avukat",),
    "bekci": ("bekci", "polis", "jandarma", "uzman erbas", "astsubay", "subay"),
}
_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20\d{2})(?!\d)")
_MONTHS = ("ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik")
_WORDED = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({'|'.join(_MONTHS)})\s+(20\d{{2}})(?!\d)")
_PUBLISHED = re.compile(
    r"(?:yayin(?:lanma)?|yayim(?:lanma)?|duyuru|eklenme|olusturulma|guncelleme|ilan)?\s*tarih[i]?\s*[:\-]?\s*"
    r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20\d{2})"
)


class SiteError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Metin yardımcıları
# ---------------------------------------------------------------------------

def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dates_in(normalized: str) -> list[date]:
    found = [_safe(int(m.group(3)), int(m.group(2)), int(m.group(1))) for m in _DATE.finditer(normalized)]
    found += [_safe(int(m.group(3)), _MONTHS.index(m.group(2)) + 1, int(m.group(1))) for m in _WORDED.finditer(normalized)]
    return [value for value in found if value]


_TITLE_DATE = re.compile(
    rf"(?:^|\s)(?:\(?(\d{{1,2}})\s*[./-]\s*(\d{{1,2}})\s*[./-]\s*(20\d{{2}})\)?|(\d{{1,2}})\s+({'|'.join(_MONTHS)})\s+(20\d{{2}})"
    rf"|({'|'.join(_MONTHS)})\s+(\d{{1,2}}),?\s+(20\d{{2}}))(?:\s+(?:detay|devami|devamini oku|tumu))?\s*$"
)


def split_title_date(title: str) -> tuple[str, date | None]:
    """Bağlantı metninin sonundaki yayın tarihini ayırır: ("... Sonuçları", 2026-11-16)."""
    normalized = normalize_text(title).strip()
    match = _TITLE_DATE.search(normalized)
    if not match:
        return title.strip(), None
    g = match.groups()
    if g[0]:
        value = _safe(int(g[2]), int(g[1]), int(g[0]))
    elif g[3]:
        value = _safe(int(g[5]), _MONTHS.index(g[4]) + 1, int(g[3]))
    else:
        value = _safe(int(g[8]), _MONTHS.index(g[6]) + 1, int(g[7]))
    if value is None:
        return title.strip(), None
    words_before = len(normalized[:match.start()].split())
    return " ".join(title.split()[:words_before]).strip(" -–|("), value


def _leading_count(title: str) -> int | None:
    """"67 sözleşmeli personel alımı" → 67. Aynı kurumun farklı alımlarını ayırt eder."""
    match = re.search(r"(?<![\d./])(\d{1,4})\s+(?:adet\s+|kisilik\s+)?(?:sozlesmeli|surekli|ogretim|arastirma|personel|memur|isci|zabita|itfaiye|uzman|mufettis|kisi)", normalize_text(title))
    return int(match.group(1)) if match and not 1990 < int(match.group(1)) < 2100 else None


def is_result_title(title: str) -> bool:
    if len(title) > 230:
        return False  # haber özeti, duyuru başlığı değil
    normalized = normalize_text(title)
    return any(word in normalized for word in _RESULT_WORDS) and not any(word in normalized for word in _UNRELATED)


def result_kind(title: str) -> str:
    text = normalize_text(title)
    if "yerlestirme" in text or "atama" in text or "atanmaya hak" in text:
        return "placement"
    if "nihai" in text or "kesin sonuc" in text or "kesin liste" in text or "basari liste" in text or "basari sira" in text or "kazanan" in text:
        return "final"
    if "sozlu" in text or "mulakat" in text:
        return "interview"
    if "yazili" in text or ("sinav sonuc" in text and "giris" not in text):
        return "exam"
    if "on degerlendirme" in text or "basvuru sonuc" in text or "sinava girmeye hak" in text or "sinava cagri" in text or "giris sinavi" in text:
        return "application"
    if "asil" in text or "yedek" in text:
        return "list"
    return "result"


def role_groups(text: str) -> set[str]:
    normalized = normalize_text(text)
    groups = {name for name, phrases in _ROLE_GROUPS.items() if any(phrase in normalized for phrase in phrases)}
    if "ogretim-elemani" in groups:
        groups |= {"ogretim-gorevlisi", "arastirma-gorevlisi"}  # genel ad: ikisini de kapsar
    if "sozlesmeli-bilisim" in groups:
        groups.discard("sozlesmeli")
    if groups - {"memur"}:
        groups.discard("memur")  # "zabıta memuru" → zabıta
    if groups - {"muhendis", "avukat", "saglik"} and len(groups) > 1:
        groups -= {"muhendis", "avukat", "saglik"}  # unvan, alım türünü belirlemez
    return groups


def _stems(text: str) -> set[str]:
    words = re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).split()
    return {word[:6] for word in words if len(word) >= 4 and word not in _GENERIC and not word.isdigit()}


def clean_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    return url[:-1] if url.endswith("/") and urlsplit(url).path != "/" else url


def site_of(host: str) -> str:
    """Alt alan adlarını yok sayarak kurumun kayıtlı alan adını verir (personel.x.edu.tr → x.edu.tr)."""
    parts = (host or "").casefold().removeprefix("www.").split(".")
    return ".".join(parts[-3:]) if len(parts) >= 3 else ".".join(parts)


# ---------------------------------------------------------------------------
# İlandan resmî adresin ve "sonuç nereden açıklanacak" bilgisinin çıkarılması
# ---------------------------------------------------------------------------

def official_source(text: str, event_urls: list[str] | None = None) -> dict:
    """İlan metninden sonuçların yayımlanacağı resmî adresi bulur.

    Dönen sözlük: url ("" olabilir), account_only (sonuç yalnızca kişisel hesapta açıklanıyor mu).
    """
    flowed = reflow_text(text or "")
    result_sentences = [s for s in _sentences(flowed) if "sonuc" in normalize_text(s)]
    account_only = any(
        any(word in normalize_text(s) for word in ("kariyer kapisi", "e-devlet", "turkiye.gov.tr"))
        for s in result_sentences
    )

    def hosts(source: str) -> list[str]:
        found = []
        for match in _HOST.finditer(source):
            host, path = match.group(1).lower(), (match.group(2) or "").rstrip(".")
            if any(shared in (host + path).lower() for shared in _SHARED_HOSTS) or host.split(".")[0] in ("mail", "posta", "eposta"):
                continue
            start = match.start()
            if start and source[start - 1] == "@":
                continue  # e-posta adresi
            found.append(f"https://{host}{path}")
        return found

    for url in event_urls or []:
        candidates = hosts(url)
        if candidates:
            return {"url": candidates[0], "account_only": account_only}
    for sentence in result_sentences:
        candidates = hosts(sentence)
        if candidates:
            return {"url": candidates[0], "account_only": account_only}
    counted: dict[str, int] = {}
    first: dict[str, str] = {}
    for url in hosts(flowed):
        site = site_of(urlsplit(url).hostname or "")
        counted[site] = counted.get(site, 0) + 1
        first.setdefault(site, url)
    if counted:
        best = max(counted, key=lambda site: (counted[site], -list(counted).index(site)))
        return {"url": first[best], "account_only": account_only}
    return {"url": "", "account_only": account_only}


# ---------------------------------------------------------------------------
# Site okuma
# ---------------------------------------------------------------------------

class SiteReader:
    """Bir tarama boyunca kurum sitelerini okur; aynı site birden çok ilan için bir kez okunur."""

    def __init__(self, fetch=None, delay: float | None = None):
        self._fetch = fetch or self._http_fetch
        self._delay = config.source_request_delay() if delay is None else delay
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._sites: dict[str, tuple[list[dict], str]] = {}
        self._pages: dict[str, dict] = {}
        self._last: dict[str, float] = {}

    def _http_fetch(self, url: str) -> dict:
        response = tls.get(url, headers=DEFAULT_HEADERS, timeout=(8, 25), stream=True)
        try:
            content_type = (response.headers.get("content-type") or "").casefold()
            body = response.raw.read(6_000_000, decode_content=True)
        finally:
            response.close()
        return {"status": response.status_code, "url": response.url, "content_type": content_type, "body": body,
                "encoding": response.encoding}

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            try:
                page = self._fetch(f"{origin}/robots.txt")
                if page["status"] == 200 and "html" not in page["content_type"]:
                    parser.parse(page["body"].decode("utf-8", "replace").splitlines())
                else:
                    parser = None  # robots.txt yok: kısıt tanımlanmamış
            except Exception:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def page(self, url: str) -> dict:
        """{"url", "links", "text", "pdf": bool} döndürür; okunamazsa SiteError."""
        url = clean_url(url)
        if url in self._pages:
            cached = self._pages[url]
            if "error" in cached:
                raise SiteError(cached["error"])
            return cached
        try:
            result = self._read(url)
        except SiteError as error:
            self._pages[url] = {"error": str(error)}
            raise
        self._pages[url] = result
        return result

    def _read(self, url: str) -> dict:
        if not self._allowed(url):
            raise SiteError("Sitenin robots.txt dosyası otomatik okumaya izin vermiyor.")
        host = urlsplit(url).netloc
        wait = self._delay - (time.monotonic() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            page = self._fetch(url)
        except requests.exceptions.SSLError:
            raise SiteError("Sitenin güvenlik sertifikası doğrulanamadı.")
        except requests.RequestException as error:
            raise SiteError(f"Siteye bağlanılamadı ({type(error).__name__}).")
        finally:
            self._last[host] = time.monotonic()
        if page["status"] in (401, 403, 429):
            raise SiteError(f"Site otomatik erişimi reddetti (HTTP {page['status']}).")
        if page["status"] != 200:
            raise SiteError(f"Sayfa açılamadı (HTTP {page['status']}).")
        body = page["body"]
        if body.startswith(b"%PDF-") or "pdf" in page["content_type"]:
            return {"url": page["url"], "links": [], "text": _pdf_text(body), "pdf": True}
        html = body.decode(page.get("encoding") or "utf-8", "replace")
        if "charset=utf-8" in html[:3000].casefold() or "charset=\"utf-8\"" in html[:3000].casefold():
            html = body.decode("utf-8", "replace")
        if any(marker in html[:5000].casefold() for marker in ("request rejected", "access denied", "captcha", "just a moment")):
            raise SiteError("Site otomatik erişimi reddetti (erişim kontrolü).")
        links, text = parse_html_page(html)
        resolved = []
        for link in links:
            href = link["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            resolved.append({"url": clean_url(absolute_url(page["url"], href)), "text": " ".join(link["text"].split())})
        return {"url": page["url"], "links": resolved, "text": text, "pdf": False}

    def site_links(self, start_url: str) -> list[dict]:
        """Kurum sitesinin başlangıç, ana ve duyuru sayfalarındaki bağlantıları toplar."""
        start_url = clean_url(start_url)
        if start_url in self._sites:
            links, error = self._sites[start_url]
            if error:
                raise SiteError(error)
            return links
        parts = urlsplit(start_url)
        root = f"{parts.scheme}://{parts.netloc}/"
        site = site_of(parts.hostname or "")
        # Bazı siteler yalnızca "www." ile (ya da onsuz) açılır; ilk adres açılmazsa diğeri denenir.
        other_host = parts.netloc[4:] if parts.netloc.startswith("www.") else f"www.{parts.netloc}"
        queue = list(dict.fromkeys([start_url, clean_url(root)]))
        fallback = clean_url(f"{parts.scheme}://{other_host}/")
        seen_pages: set[str] = set()
        links: dict[str, dict] = {}
        errors: list[str] = []
        read = 0
        while (queue or (read == 0 and fallback)) and len(seen_pages) < MAX_PAGES_PER_SITE:
            if not queue:
                queue, fallback = [fallback], ""
            url = queue.pop(0)
            if url in seen_pages:
                continue
            seen_pages.add(url)
            try:
                page = self.page(url)
            except SiteError as error:
                errors.append(str(error))
                continue
            read += 1
            for link in page["links"]:
                links.setdefault(link["url"], {**link, "found_on": page["url"]})
                target = urlsplit(link["url"])
                hint = normalize_text(f"{link['text']} {target.path}")
                if (
                    read <= 2 and site_of(target.hostname or "") == site and link["url"] not in seen_pages
                    and not target.path.casefold().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".jpg", ".png"))
                    and any(word in hint for word in _INDEX_HINTS) and len(link["text"]) < 60
                    and not is_result_title(link["text"])
                ):
                    queue.append(link["url"])
        result = list(links.values())
        if read == 0:
            error = errors[0] if errors else "Site okunamadı."
        elif len(result) < 8:
            error = "Sayfa içeriği otomatik okunamadı (site JavaScript ile yükleniyor olabilir)."
        else:
            error = ""
        self._sites[start_url] = (result, error)
        if error:
            raise SiteError(error)
        return result


def _pdf_text(body: bytes) -> str:
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(body)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages[:3])
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Eşleştirme
# ---------------------------------------------------------------------------

def job_profile(job: Job, position_titles: list[str], event_dates: list[date]) -> dict:
    title_text = " ".join([job.title, *position_titles[:12]])
    start = job.application_start or job.announcement_date or (
        job.application_deadline - timedelta(days=45) if job.application_deadline else None
    )
    return {
        "id": job.id,
        "roles": role_groups(job.title) or role_groups(title_text) or ({"ogretim-elemani", "ogretim-gorevlisi", "arastirma-gorevlisi", "ogretim-uyesi"} if is_academic_listing(job.title) else set()),
        "count": _leading_count(job.title),
        "stems": _stems(job.title),
        "position_stems": _stems(" ".join(position_titles[:12])),
        "start": start,
        "deadline": job.application_deadline,
        "reference_dates": {value for value in (job.application_start, job.application_deadline, *event_dates) if value},
    }


def score_candidate(profile: dict, title: str, text: str, published: date | None, today: date) -> dict | None:
    """Duyurunun bu ilana ait olma olasılığını değerlendirir; ilgisizse None."""
    title, title_date = split_title_date(title)
    published = published or (title_date if title_date and title_date <= today else None)
    normalized_title = normalize_text(title)
    if not is_result_title(title):
        return None
    reasons: list[str] = []
    count = _leading_count(title)
    if count and profile.get("count") and count != profile["count"]:
        return None  # kişi sayısı farklı: başka bir alım
    candidate_roles = role_groups(title)
    if candidate_roles and profile["roles"] and not (candidate_roles & profile["roles"]):
        return None  # aynı kurumun başka bir alımı
    start, deadline = profile["start"], profile["deadline"]
    years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized_title)}
    job_years = {value.year for value in (start, deadline) if value}
    if years and job_years and not (years & {*job_years, *(year + 1 for year in job_years)}):
        return None  # başlıktaki yıl başka bir döneme ait
    mentioned = dates_in(normalize_text(f"{title}\n{text[:6000]}"))
    if published is None and mentioned:
        past = [value for value in mentioned if value <= today]
        published_guess = max(past) if past else None
    else:
        published_guess = published
    if published_guess and start and published_guess < start:
        return None  # ilandan önce yayımlanmış: önceki bir alımın sonucu
    if published_guess and deadline and published_guess > deadline + timedelta(days=TRACK_DAYS + 60):
        return None

    same_role = bool(candidate_roles & profile["roles"])
    candidate_stems = _stems(title)
    overlap = len(profile["stems"] & candidate_stems) / max(1, len(profile["stems"]))
    position_hit = bool(profile["position_stems"] & candidate_stems)
    # Yalnızca ilan/başvuru/sınav bağlamındaki satırlarda geçen tarihler kanıt sayılır;
    # sayfanın kenarındaki "ilgili haberler" tarihleri sayılmaz.
    contextual: set[date] = set()
    for line in f"{title}\n{text[:8000]}".splitlines():
        normalized_line = normalize_text(line)
        if any(word in normalized_line for word in ("ilan", "basvuru", "sinav", "mulakat", "tarihli", "alim")):
            contextual.update(dates_in(normalized_line))
    strong = sorted(value for value in profile["reference_dates"] if value in contextual and value != published)
    if same_role:
        reasons.append("Kadro türü aynı")
    if overlap >= 0.5:
        reasons.append("Başlık ilanla örtüşüyor")
    if position_hit:
        reasons.append("Unvan duyuruda geçiyor")
    if strong:
        reasons.append("Duyuruda ilanın tarihleri geçiyor: " + ", ".join(value.strftime("%d.%m.%Y") for value in strong[:3]))
    if published and start and published >= start:
        reasons.append(f"İlandan sonra yayımlanmış ({published:%d.%m.%Y})")
    if not (same_role or overlap >= 0.5 or position_hit or strong):
        return None
    confident = bool(strong) and (same_role or overlap >= 0.34 or position_hit) or (
        same_role and overlap >= 0.6 and published is not None
    )
    weight = (3 if strong else 0) + (2 if same_role else 0) + overlap + (1 if position_hit else 0)
    return {"confident": confident, "weight": weight, "reasons": reasons, "published": published or None}


def _published_date(page_text: str, url: str, today: date) -> date | None:
    normalized = normalize_text(page_text[:4000])
    match = _PUBLISHED.search(normalized)
    if match:
        value = _safe(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if value and value <= today:
            return value
    in_url = re.search(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:/|-|$)", url)
    if in_url:
        value = _safe(int(in_url.group(1)), int(in_url.group(2)), int(in_url.group(3)))
        if value and value <= today:
            return value
    return None


# ---------------------------------------------------------------------------
# Takip
# ---------------------------------------------------------------------------

def _texts(db: Session, jobs: list[Job]) -> str:
    parts = [job.description or "" for job in jobs]
    ids = [job.id for job in jobs]
    for document in db.scalars(select(JobDocument).where(JobDocument.job_id.in_(ids))).all():
        if document.extracted_text and document.status != "obsolete":
            parts.append(document.extracted_text)
    return "\n".join(parts)


def _position_titles(db: Session, job_ids: list[int]) -> list[str]:
    rows = db.execute(
        select(DocumentPosition.position_title).join(JobDocument, JobDocument.id == DocumentPosition.document_id)
        .where(JobDocument.job_id.in_(job_ids))
    ).all()
    return list(dict.fromkeys(row[0] for row in rows if row[0]))


def tracked_jobs(db: Session, today: date) -> list[dict]:
    """Sonucu izlenecek ilanlar: başvurusu bitmiş, sonuçlanmamış, tekil ilanlar. Başvurulanlar önce gelir."""
    from .matching import _duplicate_groups

    jobs = list(db.scalars(select(Job).where(Job.sector == "public", Job.archived_reason == "")).all())
    hidden, copies = _duplicate_groups(jobs)
    states = {state.job_id: state.tracking for state in db.scalars(select(UserJobState)).all()}
    trackings = {row.job_id: row for row in db.scalars(select(ResultTracking)).all()}
    finals = set(db.scalars(select(ResultAnnouncement.job_id).where(
        ResultAnnouncement.kind.in_(FINAL_KINDS), ResultAnnouncement.match_status == "matched",
        ResultAnnouncement.user_decision != "rejected",
    )).all())
    selected = []
    for job in jobs:
        if job.id in hidden or not job.is_employment or job.status == "İptal edildi":
            continue
        family = [job, *copies.get(job.id, [])]
        tracking = next((states[m.id] for m in family if states.get(m.id)), "")
        if tracking in ("hidden", "won", "lost"):
            continue
        deadline = job.application_deadline
        applied = tracking in ("applied", "awaiting")
        if deadline is None:
            if not applied:
                continue
        elif deadline >= today and not applied:
            continue  # başvuru sürüyor: sonuç henüz olamaz
        elif (today - deadline).days > TRACK_DAYS and not applied:
            continue
        if job.id in finals and not applied:
            continue
        priority = 0 if applied else 1 if tracking == "saved" else 2
        last = trackings[job.id].last_checked_at if job.id in trackings else None
        selected.append({"job": job, "family": family, "tracking": tracking, "priority": priority, "last": last or datetime.min})
    selected.sort(key=lambda item: (item["priority"], item["last"], item["job"].id))
    return selected


def check_job(db: Session, entry: dict, reader: SiteReader, peers: list[dict], today: date) -> dict:
    """Tek ilanın resmî sitesini kontrol eder ve bulunan sonuç duyurularını kaydeder."""
    job: Job = entry["job"]
    family_ids = [member.id for member in entry["family"]]
    now = clock.now()
    tracking = db.get(ResultTracking, job.id)
    if tracking is None:
        tracking = ResultTracking(job_id=job.id)
        db.add(tracking)
    events = db.scalars(select(JobEvent).where(JobEvent.job_id.in_(family_ids), JobEvent.deleted.is_(False))).all()
    source = official_source(_texts(db, entry["family"]), [event.url for event in events if event.kind == "result" and event.url])
    tracking.account_only = source["account_only"]
    tracking.source_url = tracking.manual_url or source["url"]
    tracking.last_checked_at = now
    if not tracking.source_url:
        tracking.status, tracking.detail = "no_source", ""
        return {"status": "no_source", "found": 0}
    try:
        links = reader.site_links(tracking.source_url)
    except SiteError as error:
        tracking.status, tracking.detail = "error", str(error)[:500]
        return {"status": "error", "found": 0}

    profile = entry.setdefault("profile", job_profile(
        job, _position_titles(db, family_ids), [event.event_date for event in events if event.kind in ("exam", "interview")],
    ))
    known = {row.url: row for row in db.scalars(select(ResultAnnouncement).where(ResultAnnouncement.job_id == job.id)).all()}
    found = details = 0
    for link in links:
        title = link["text"]
        if len(title) < 8 or link["url"] in known or not is_result_title(title):
            continue
        if score_candidate(profile, title, "", None, today) is None:
            continue
        if details >= MAX_DETAILS_PER_JOB:
            break
        details += 1
        text, published, document_url = "", None, ""
        try:
            page = reader.page(link["url"])
            text = page["text"]
            if page["pdf"]:
                document_url = link["url"]
            else:
                published = _published_date(text, link["url"], today)
                document_url = next((
                    item["url"] for item in page["links"]
                    if urlsplit(item["url"]).path.casefold().endswith((".pdf", ".xlsx", ".xls", ".docx"))
                    and (is_result_title(item["text"]) or "liste" in normalize_text(item["text"]) or len(page["links"]) < 80)
                    and item["url"] not in {entry_link["url"] for entry_link in links}
                ), "")
        except SiteError:
            pass  # başlıkla değerlendirilir; kesin eşleşme sayılmaz
        scored = score_candidate(profile, title, text, published, today)
        if scored is None:
            continue
        # Aynı kurumun başka bir ilanı bu duyuruya benzer ölçüde uyuyorsa eşleşme kesin sayılmaz.
        rivals = [
            other for other in peers
            if other["job"].id != job.id and "profile" in other
            and (rival := score_candidate(other["profile"], title, text, published, today)) is not None
            and rival["weight"] > scored["weight"] - 1  # tarih kanıtı (3 puan) belirsizliği giderir
        ]
        confident = scored["confident"] and not rivals
        reasons = scored["reasons"] + (["Kurumun benzer başka bir ilanı var"] if rivals else [])
        db.add(ResultAnnouncement(
            job_id=job.id, url=link["url"][:1200], title=split_title_date(title)[0][:500], kind=result_kind(title),
            published_date=scored["published"], document_url=document_url[:1200], found_on=link.get("found_on", "")[:1200],
            match_status="matched" if confident else "needs_review",
            match_reasons=json.dumps(reasons, ensure_ascii=False), found_at=now,
        ))
        known[link["url"]] = None
        found += 1
    tracking.status, tracking.detail, tracking.last_success_at = "checked", "", now
    return {"status": "checked", "found": found}


def check_results(db: Session, *, today: date | None = None, reader: SiteReader | None = None,
                  limit: int = 60, time_budget: float = 420.0, on_progress=None) -> dict:
    """Sonuç takibindeki ilanları kontrol eder. Başvurulan ilanlar her taramada, diğerleri sırayla."""
    from .sync import organization_key

    today = today or clock.today()
    reader = reader or SiteReader()
    entries = tracked_jobs(db, today)
    by_org: dict[str, list[dict]] = {}
    for entry in entries:
        by_org.setdefault(organization_key(entry["job"].organization), []).append(entry)
        family_ids = [member.id for member in entry["family"]]
        exam_dates = [event.event_date for event in db.scalars(select(JobEvent).where(
            JobEvent.job_id.in_(family_ids), JobEvent.deleted.is_(False), JobEvent.kind.in_(("exam", "interview")),
        )).all()]
        entry["profile"] = job_profile(entry["job"], _position_titles(db, family_ids), exam_dates)
    report = {"tracked": len(entries), "checked": 0, "found": 0, "errors": 0, "no_source": 0, "skipped": 0}
    started = time.monotonic()
    for index, entry in enumerate(entries):
        over_budget = time.monotonic() - started > time_budget or report["checked"] + report["errors"] >= limit
        if over_budget and entry["priority"] > 0:
            report["skipped"] += 1
            continue
        if on_progress:
            on_progress("Sonuç duyuruları", index + 1, len(entries))
        try:
            outcome = check_job(db, entry, reader, by_org[organization_key(entry["job"].organization)], today)
            db.commit()
        except Exception:  # tek ilandaki beklenmeyen hata takibi durdurmaz
            db.rollback()
            logger.exception("Result check failed for job %s", entry["job"].id)
            outcome = {"status": "error", "found": 0}
        report["found"] += outcome["found"]
        key = {"checked": "checked", "error": "errors", "no_source": "no_source"}[outcome["status"]]
        report[key] += 1
    return report


# ---------------------------------------------------------------------------
# Arayüz için durum
# ---------------------------------------------------------------------------

def announcement_payload(row: ResultAnnouncement) -> dict:
    try:
        reasons = json.loads(row.match_reasons or "[]")
    except ValueError:
        reasons = []
    confirmed = row.user_decision == "confirmed"
    return {
        "id": row.id, "job_id": row.job_id, "title": row.title, "url": row.url, "document_url": row.document_url or None,
        "kind": row.kind, "kind_label": KIND_LABELS.get(row.kind, KIND_LABELS["result"]),
        "published_date": row.published_date.isoformat() if row.published_date else None,
        "found_at": row.found_at.isoformat(timespec="seconds"),
        "match_status": "matched" if confirmed else row.match_status,
        "user_confirmed": confirmed, "reasons": reasons,
    }


def job_result_status(db: Session, job: Job, tracking_state: str, today: date | None = None) -> dict:
    """İlanın sonuç takibi durumu: açık bir kod ve kullanıcıya gösterilecek cümle."""
    today = today or clock.today()
    rows = db.scalars(select(ResultAnnouncement).where(
        ResultAnnouncement.job_id == job.id, ResultAnnouncement.user_decision != "rejected",
    ).order_by(ResultAnnouncement.found_at.desc(), ResultAnnouncement.id.desc())).all()
    announcements = [announcement_payload(row) for row in rows]
    tracking = db.get(ResultTracking, job.id)
    expected = db.scalar(select(JobEvent.event_date).where(
        JobEvent.job_id == job.id, JobEvent.kind == "result", JobEvent.deleted.is_(False), JobEvent.event_date >= today,
    ).order_by(JobEvent.event_date).limit(1))
    checked = tracking.last_checked_at.isoformat(timespec="seconds") if tracking and tracking.last_checked_at else None
    base = {
        "announcements": announcements,
        "source_url": (tracking.source_url if tracking else "") or None,
        "manual_url": (tracking.manual_url if tracking else "") or None,
        "last_checked_at": checked,
        "last_success_at": tracking.last_success_at.isoformat(timespec="seconds") if tracking and tracking.last_success_at else None,
        "account_only": bool(tracking and tracking.account_only),
        "expected_date": expected.isoformat() if expected else None,
    }
    account_note = " İlana göre sonuç ayrıca Kariyer Kapısı / e-Devlet hesabında açıklanır; oradan da kontrol et." if base["account_only"] else ""
    deadline = job.application_deadline
    if any(item["match_status"] == "matched" for item in announcements):
        code, message = "found", "Resmî sonuç duyurusu bulundu."
    elif announcements:
        code, message = "needs_review", "Olası bir sonuç duyurusu bulundu ancak bu ilana ait olduğu doğrulanamadı. Eşleşme doğrulanmalı."
    elif tracking_state in ("won", "lost"):
        code, message = "closed", "Bu ilanı sonuçlandırdın; sonuç araması durduruldu."
    elif deadline and deadline >= today and tracking_state not in ("applied", "awaiting"):
        code, message = "waiting", "Başvuru süresi bitmedi; sonuç araması son başvuru gününden sonra başlar."
    elif tracking is None or tracking.status == "pending" or tracking.last_checked_at is None:
        code, message = "pending", "Bu ilan sonuç takibinde; kurumun sitesi henüz kontrol edilmedi. Sonraki taramada kontrol edilecek."
    elif tracking.status == "no_source":
        code = "no_source"
        message = ("İlan metninde kurumun sonuçları yayımlayacağı bir internet adresi bulunamadı; otomatik kontrol yapılamıyor. "
                   "Adresi aşağıya eklersen düzenli kontrol edilir.")
    elif tracking.status == "error":
        code = "error"
        message = f"Kaynak kontrol edilemedi: {tracking.detail or 'bilinmeyen hata'} Bu, sonuç yayımlanmadığı anlamına gelmez; resmî siteyi kendin kontrol et."
    elif expected:
        code = "not_due"
        message = f"Henüz sonuç duyurusu yayımlanmamış. İlana göre sonuç {expected:%d.%m.%Y} tarihinde açıklanacak; kurumun sitesi düzenli kontrol ediliyor."
    else:
        code = "not_found"
        message = "Bu ilan için henüz resmî sonuç duyurusu bulunamadı. Kurumun duyuruları düzenli olarak kontrol edilmeye devam ediyor."
    return {**base, "status": code, "message": message + (account_note if code not in ("found", "closed") else "")}
