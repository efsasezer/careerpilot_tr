"""ÖSYM duyuruları – KPSS merkezi yerleştirme (tercih) duyuruları.

Merkezi yerleştirme kadroları ÖSYM'nin tercih kılavuzunda yayımlanır. Bu kaynak ÖSYM ana
sayfasındaki duyurulardan KPSS/EKPSS tercih dönemlerini yakalar ve ilan havuzuna ekler ki aday
tercih dönemini kaçırmasın. Kılavuzdaki binlerce kadro satırı tek tek ayrıştırılmaz; kılavuz
bağlantısı ilanla birlikte gösterilir ve ilan "inceleme gerekli" olarak kalır.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .. import tls
from ..eligibility import normalize_text
from .base import DEFAULT_HEADERS, BaseJobSource, SourceFetchError, absolute_url, content_hash, parse_html_page

_PLACEMENT = re.compile(r"\b(?:e?kpss)\b.*\btercih", re.S)
_NOT_PLACEMENT = ("sinav merkez", "sonuclari", "sonuclarin", "siralama", "basvuru kilavuzu")


def is_placement_announcement(title: str) -> bool:
    normalized = normalize_text(title)
    return bool(_PLACEMENT.search(normalized)) and not any(word in normalized for word in _NOT_PLACEMENT)


class OsymSource(BaseJobSource):
    source_name = "ÖSYM"
    base_url = "https://www.osym.gov.tr/"
    # Tercih dönemi yokken hiç duyuru bulunmaması olağandır.
    allow_empty = True

    def _get(self, url: str) -> tuple[str, str]:
        try:
            response = tls.get(url, headers=DEFAULT_HEADERS, timeout=(8, 40))
        except Exception as error:
            raise SourceFetchError(self.source_name, url, str(error)) from error
        if response.status_code != 200:
            raise SourceFetchError(self.source_name, url, "Sayfa alınamadı.", response.status_code)
        response.encoding = response.apparent_encoding or response.encoding
        return response.url, response.text

    def fetch_listings(self) -> list[dict[str, Any]]:
        final_url, html = self._get(self.base_url)
        links, _ = parse_html_page(html)
        self.pages_checked = 1
        if len(links) < 20:
            raise RuntimeError("ÖSYM ana sayfası beklenen duyuru bağlantılarını içermiyor; sayfa yapısı değişmiş olabilir.")
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for link in links:
            title = " ".join(link["text"].split())
            url = absolute_url(final_url, link["href"])
            parsed = urlsplit(url)
            if (
                not is_placement_announcement(title)
                or parsed.hostname not in ("www.osym.gov.tr", "osym.gov.tr")
                or parsed.path.casefold().endswith((".pdf", ".docx", ".xlsx"))
                or url in seen
            ):
                continue
            seen.add(url)
            results.append(self.normalize_listing({
                "source_key": "osym",
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": url,
                "external_id": parsed.path.strip("/")[:280] or url,
                "title": title,
                "institution": "ÖSYM (KPSS Merkezi Yerleştirme)",
                "recruitment_method": "KPSS merkezi yerleştirme",
                "content_hash": content_hash(title),
            }))
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        final_url, html = self._get(url)
        links, text = parse_html_page(html)
        if len(text) < 80:
            raise RuntimeError("ÖSYM duyurusunda ayrıştırılabilir metin yok.")
        attachments = []
        for link in links:
            href = absolute_url(final_url, link["href"])
            if urlsplit(href).path.casefold().endswith((".pdf", ".xlsx", ".docx")) and "osym.gov.tr" in (urlsplit(href).hostname or ""):
                title = " ".join(link["text"].split()) or "ÖSYM belgesi"
                if href not in [item["url"] for item in attachments]:
                    attachments.append({
                        "url": href, "title": title[:200],
                        "error": "Tercih kılavuzu otomatik ayrıştırılmıyor; kadroları ve nitelik kodlarını kılavuzdan kontrol edin.",
                    })
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
            "unread_attachments": attachments[:8],
        }
