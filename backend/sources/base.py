"""Genişletilebilir kamu ilanı kaynak mimarisi.

Her kaynak `fetch_listings()` ile liste kayıtlarını, `fetch_detail()` ile ilanın
ayrıntılı metnini (HTML sayfası veya resmî PDF/DOCX belgesi) döndürür.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import time
from typing import Any, Dict, List
from urllib.parse import urljoin

import requests


ERROR_KINDS = {
    "dns": "Alan adı çözülemedi (DNS)",
    "connect_timeout": "Sunucu bağlantıyı kabul etmedi (bağlantı zaman aşımı)",
    "read_timeout": "Sunucu yanıtı zamanında göndermedi (okuma zaman aşımı)",
    "connection": "Bağlantı kurulamadı ya da kesildi",
    "tls": "Güvenlik sertifikası doğrulanamadı (TLS)",
    "http_403": "Sunucu isteği reddetti (HTTP 403)",
    "http_404": "Sayfa bulunamadı (HTTP 404)",
    "http_429": "İstek sınırı aşıldı (HTTP 429)",
    "http_5xx": "Kaynak sunucusunda hata (HTTP 5xx)",
    "http_other": "Beklenmeyen HTTP yanıtı",
    "blocked": "Erişim kontrolü sayfası döndü",
    "browser_timeout": "Sayfa tarayıcıda zamanında yüklenmedi",
    "structure": "Sayfa yapısı beklenenden farklı",
    "unknown": "Bilinmeyen hata",
}
# Uygulamanın çalıştığı sunucunun konumuna bağlı olabilen hata türleri: kaynak, Türkiye dışındaki
# sunuculardan gelen istekleri reddediyor ya da yanıtsız bırakıyor olabilir.
LOCATION_SENSITIVE_KINDS = {"dns", "connect_timeout", "connection", "http_403", "blocked", "browser_timeout"}


def classify_error(error: BaseException | None = None, status_code: int | None = None) -> str:
    """Bir tarama hatasını türüne ayırır (DNS / zaman aşımı / TLS / HTTP durum kodu ...)."""
    kind = getattr(error, "kind", None)
    if kind in ERROR_KINDS:
        return kind
    status_code = status_code if status_code is not None else getattr(error, "status_code", None)
    if status_code:
        if status_code in (401, 403):
            return "http_403"
        if status_code == 404:
            return "http_404"
        if status_code == 429:
            return "http_429"
        return "http_5xx" if status_code >= 500 else "http_other"
    text = f"{type(error).__name__} {error}".casefold()
    seen: set[int] = set()
    while error is not None and id(error) not in seen:  # sarmalanmış asıl nedeni de incele
        seen.add(id(error))
        text += f" {type(error).__name__} {error}".casefold()
        error = error.__cause__ or error.__context__
    if any(marker in text for marker in ("nameresolution", "name or service not known", "nodename nor servname", "getaddrinfo", "err_name_not_resolved", "temporary failure in name resolution")):
        return "dns"
    if "ssl" in text or "certificate" in text or "err_cert" in text:
        return "tls"
    if "connecttimeout" in text or "connect timeout" in text or "err_connection_timed_out" in text or "err_timed_out" in text:
        return "connect_timeout"
    if "readtimeout" in text or "read timed out" in text:
        return "read_timeout"
    if "wait_for_function" in text or "wait_for_selector" in text or ("timeout" in text and ("page." in text or "locator" in text or "playwright" in text)):
        return "browser_timeout"
    if "connectionerror" in text or "connection refused" in text or "connection reset" in text or "err_connection" in text or "remotedisconnected" in text:
        return "connection"
    if "timeout" in text or "timed out" in text:
        return "read_timeout"
    return "unknown"


class SourceFetchError(RuntimeError):
    def __init__(self, source_name: str, url: str, message: str, status_code: int | None = None, kind: str | None = None):
        self.source_name = source_name
        self.url = url
        self.status_code = status_code
        self.kind = kind or classify_error(None, status_code) if (kind or status_code) else None
        status = f" HTTP {status_code}" if status_code is not None else ""
        super().__init__(f"{source_name}:{status} {url}: {message}")


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self._link: dict[str, str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if tag == "a":
            self._link = {"href": values.get("href", ""), "text": ""}
        if tag in {"br", "p", "div", "tr", "td", "th", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "a" and self._link is not None:
            self._link["text"] = " ".join(self._link["text"].split())
            if self._link["href"]:
                self.links.append(self._link)
            self._link = None
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = data.strip()
        if not text:
            return
        self.text_parts.append(f"{text} ")
        if self._link is not None:
            self._link["text"] += f" {text}"


def parse_html_page(html: str) -> tuple[list[dict[str, str]], str]:
    parser = _PageParser()
    parser.feed(html)
    text = "".join(parser.text_parts)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return parser.links, "\n".join(line for line in lines if line)


MIN_DOCUMENT_TEXT = 80
USER_AGENT = "CareerPilotTR/1.0 (public job listing index)"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_WAIT = 30.0


def _retry_wait(response, attempt: int) -> float:
    """Sunucunun Retry-After isteğine uyar; yoksa üstel bekleme (1, 3 sn). Üst sınır 30 sn."""
    header = (response.headers.get("Retry-After") or "").strip() if response is not None else ""
    if header.isdigit():
        return min(float(header), MAX_RETRY_WAIT)
    return min(1.0 * 3 ** attempt, MAX_RETRY_WAIT)


def fetch_html(source_name: str, url: str, session: requests.Session | None = None, *, sleep=time.sleep) -> tuple[str, str]:
    """Bir kaynak sayfasını alır.

    - Bağlantı/zaman aşımı hataları ile 429 ve 5xx yanıtları sınırlı sayıda yeniden denenir.
    - 403 ve 404 yeniden denenmez: aynı isteği yinelemek sonucu değiştirmez ve kaynağı yorar.
    - Sertifika zinciri eksikse doğrulama kapatılmaz; `tls.get` zinciri doğrulanmış biçimde tamamlar.
    - Başarısız ya da engellenmiş yanıt asla boş ilan listesi gibi döndürülmez; hata türüyle birlikte yükseltilir.
    """
    from .. import tls

    response = None
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = tls.get(url, session=session, timeout=(15, 40), headers=DEFAULT_HEADERS)
        except requests.RequestException as error:
            last_error, response = error, None
            if classify_error(error) == "tls" or attempt == MAX_ATTEMPTS - 1:
                break  # sertifika hatası beklemekle düzelmez
            sleep(_retry_wait(None, attempt))
            continue
        if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
            sleep(_retry_wait(response, attempt))
            continue
        break
    if response is None:
        raise SourceFetchError(source_name, url, str(last_error), kind=classify_error(last_error)) from last_error
    if response.status_code != 200:
        raise SourceFetchError(source_name, url, "Kaynak sayfası alınamadı.", response.status_code)
    response.encoding = response.apparent_encoding or response.encoding
    body = response.text
    rejected = any(
        marker in body.casefold()
        for marker in ("request rejected", "access denied", "captcha", "robot check")
    )
    if rejected:
        raise SourceFetchError(source_name, url, "Kaynak erişim kontrolü isteği reddetti.", response.status_code, kind="blocked")
    return response.url, body


def pdf_is_scanned(body: bytes) -> bool:
    """Sayfaları görüntüden oluşan ve neredeyse hiç metin içermeyen PDF: taranmış belge."""
    if not body.startswith(b"%PDF-"):
        return False
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(body)) as pdf:
            pages = pdf.pages[:5]
            image_pages = sum(1 for page in pages if page.images)
            characters = sum(len(page.chars) for page in pages)
        return bool(pages) and image_pages >= max(1, len(pages) // 2) and characters < MIN_DOCUMENT_TEXT * len(pages)
    except Exception:
        return False


def absolute_url(page_url: str, href: str) -> str:
    return urljoin(page_url, href.strip())


def content_hash(*parts: str) -> str:
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


def external_id(url: str) -> str:
    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ("id", "i", "kod"):
        if query.get(key):
            return query[key][0]
    return parsed.path.rstrip("/").rsplit("/", 1)[-1] or url


class BaseJobSource(ABC):
    """Tüm ilan kaynakları için ortak arayüz."""

    source_name: str = ""
    base_url: str = ""
    pages_checked: int = 0

    def __init__(self) -> None:
        self.fetch_warnings: list[str] = []

    def add_fetch_warning(self, message: str) -> None:
        if "fetch_warnings" not in self.__dict__:
            self.fetch_warnings = []
        self.fetch_warnings.append(str(message)[:400])

    @staticmethod
    def normalize_listing(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Dört kaynak için standart alan setini hazırlar."""
        payload = dict(raw)
        payload.setdefault("source_name", "")
        payload.setdefault("source_url", "")
        payload.setdefault("detail_url", "")
        payload.setdefault("title", "")
        payload.setdefault("institution", "")
        payload.setdefault("position_title", "")
        payload.setdefault("city", None)
        payload.setdefault("quota", None)
        payload.setdefault("announcement_date", None)
        payload.setdefault("application_start_date", None)
        payload.setdefault("application_end_date", None)
        payload.setdefault("employment_type", "")
        payload.setdefault("description_html", "")
        payload.setdefault("source_status", "unknown")
        payload.setdefault("first_seen_at", None)
        payload.setdefault("last_checked_at", datetime.now(timezone.utc).isoformat())
        payload.setdefault("content_hash", "")
        payload.setdefault("metadata", {})
        return payload

    @staticmethod
    def document_detail(url: str, body: bytes, content_type: str, title: str = "") -> Dict[str, Any]:
        """Detayı doğrudan resmî belge (PDF/DOCX) olan ilanlar için ortak ayrıştırma."""
        from ..documents import DocumentParseError, ScannedDocumentError, parse_document

        try:
            parsed = parse_document(url, body, content_type)
            # Taranmış PDF'lerde yalnızca kaşe/sayfa numarası gibi birkaç karakterlik metin katmanı
            # olabilir. Bunu "okundu" saymak ilanı boş gösterir; taranmış belge olarak ele alınır.
            if len((parsed.get("text") or "").strip()) < MIN_DOCUMENT_TEXT and pdf_is_scanned(body):
                raise DocumentParseError("PDF'te okunabilir metin katmanı yok (taranmış belge).")
        except DocumentParseError as error:
            if not body.startswith(b"%PDF-"):
                raise
            # Metin katmanı yok: taranmış PDF. OCR denenir; olmazsa ilan "okunamadı" kalır.
            from ..ocr import OcrUnavailable, ocr_pdf

            try:
                scanned = ocr_pdf(body)
            except OcrUnavailable as unavailable:
                raise ScannedDocumentError(f"Taranmış PDF okunamadı: {unavailable}") from error
            except Exception as failure:  # OCR hatası taramayı durdurmaz
                raise ScannedDocumentError(f"Taranmış PDF okunamadı: OCR hatası ({failure})") from error
            parsed = {
                "text": scanned["text"], "shared_requirements": "", "positions": [], "links": [],
                "partially_read": True, "ocr_confidence": scanned["confidence"],
            }
        return {
            "source_text": parsed["text"],
            "content_hash": sha256(body).hexdigest(),
            "detail_url": url,
            "document": {
                "url": url,
                "title": title or "Resmî ilan metni",
                "content_type": content_type,
                "body_hash": sha256(body).hexdigest(),
                "parsed": parsed,
            },
        }

    def fetch_detail(self, url: str) -> Dict[str, Any]:
        final_url, html = fetch_html(self.source_name, url)
        _, text = parse_html_page(html)
        if len(text) < 80:
            raise SourceFetchError(
                self.source_name,
                final_url,
                "İlan detayında ayrıştırılabilir metin bulunamadı.",
            )
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
        }

    @abstractmethod
    def fetch_listings(self) -> List[Dict[str, Any]]:
        """İlanları çeker ve standart alanlar içeren sözlük listesi döndürür."""
