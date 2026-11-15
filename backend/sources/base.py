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


class SourceFetchError(RuntimeError):
    def __init__(self, source_name: str, url: str, message: str, status_code: int | None = None):
        self.source_name = source_name
        self.url = url
        self.status_code = status_code
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


USER_AGENT = "CareerPilotTR/1.0 (public job listing index)"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


def fetch_html(source_name: str, url: str, session: requests.Session | None = None) -> tuple[str, str]:
    client = session or requests
    response = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.get(url, timeout=(8, 30), headers=DEFAULT_HEADERS)
            break
        except requests.RequestException as error:
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    if response is None:
        raise SourceFetchError(source_name, url, str(last_error)) from last_error
    if response.status_code != 200:
        raise SourceFetchError(source_name, url, "Kaynak sayfası alınamadı.", response.status_code)
    response.encoding = response.apparent_encoding or response.encoding
    body = response.text
    rejected = any(
        marker in body.casefold()
        for marker in ("request rejected", "access denied", "captcha", "robot check")
    )
    if rejected:
        raise SourceFetchError(source_name, url, "Kaynak erişim kontrolü isteği reddetti.", response.status_code)
    return response.url, body


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
        from ..documents import parse_document

        parsed = parse_document(url, body, content_type)
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
