from __future__ import annotations

from datetime import date
import re
from typing import Any
from urllib.parse import urlsplit

from ..eligibility import normalize_text
from .base import (
    BaseJobSource,
    absolute_url,
    content_hash,
    fetch_html,
    parse_html_page,
)

_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7,
    "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}
_LEADING_DATE = re.compile(
    r"^\s*(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})\s*"
    r"(?:Pazartesi|Salı|Çarşamba|Perşembe|Cuma|Cumartesi|Pazar)?\s*",
)
# Yalnızca personel alımı duyuruları ilan sayılır; rehber, görüş ve form sayfaları alınmaz.
_RECRUITMENT_WORDS = ("alim", "alacak", "atanmak uzere", "memur", "zabita", "itfaiye", "personel alim", "isci")


def parse_announcement_title(raw_title: str) -> dict[str, Any]:
    """"05 Kasım 2026 Perşembe NİĞDE İLİ BOZKÖY BELEDİYE BAŞKANLIĞINA ... İLANI..." satırını ayrıştırır."""
    title = " ".join((raw_title or "").split()).rstrip(". ").strip()
    announced = None
    match = _LEADING_DATE.match(title)
    if match:
        month = _MONTHS.get(normalize_text(match.group(2)))
        if month:
            try:
                announced = date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                announced = None
            title = title[match.end():].strip()

    city = ""
    city_match = re.match(r"^([A-ZÇĞİÖŞÜ]+)\s+İLİ\b", title)
    if city_match:
        city = _title_case(city_match.group(1))

    institution = ""
    org_match = re.search(
        r"^(.*?\b(?:BELEDİYESİ|BELEDİYE BAŞKANLIĞI|İL ÖZEL İDARESİ|BİRLİĞİ|İLÇESİ))",
        title.replace("BAŞKANLIĞINA", "BAŞKANLIĞI").replace("BELEDİYESİNE", "BELEDİYESİ"),
    )
    if org_match:
        institution = re.sub(r"^\S+ İli ", "", _title_case(org_match.group(1)))

    normalized = normalize_text(title)
    return {
        "title": title,
        "announcement_date": announced,
        "city": city,
        "institution": institution,
        "is_recruitment": (
            any(word in normalized for word in _RECRUITMENT_WORDS)
            and "ilan" in normalized
            and not any(word in normalized for word in ("form", "rehber", "gorus", "mevzuat"))
        ),
        "is_cancellation": "iptal" in normalized,
    }


def _title_case(value: str) -> str:
    lowered = value.replace("I", "ı").replace("İ", "i").lower()
    words = []
    for word in lowered.split():
        first = {"i": "İ", "ı": "I"}.get(word[0], word[0].upper())
        words.append(first + word[1:])
    return " ".join(words)


class YerelYonetimlerSource(BaseJobSource):
    source_name = "Yerel Yönetimler Genel Müdürlüğü"
    base_url = "https://yerelyonetimler.csb.gov.tr/duyurular"
    announcement_pattern = re.compile(r"-duyuru-(\d+)(?:/|$)", re.I)
    page_pattern = re.compile(r"/duyurular/(\d+)/?$", re.I)
    max_pages = 5

    def fetch_listings(self) -> list[dict[str, Any]]:
        first_url, first_html = fetch_html(self.source_name, self.base_url)
        first_links, _ = parse_html_page(first_html)
        page_numbers = {1}
        for link in first_links:
            page_url = absolute_url(first_url, link["href"])
            match = self.page_pattern.search(urlsplit(page_url).path)
            if match:
                page_numbers.add(int(match.group(1)))
        last_page = max(page_numbers)
        if last_page > 100:
            raise RuntimeError(f"Sayfalama beklenmeyen biçimde çok büyük: {last_page}")

        pages = [(first_url, first_links)]
        # Güncel ilanlar ilk sayfalardadır; eski duyuruların tamamı taranmaz.
        for page_number in range(2, min(last_page, self.max_pages) + 1):
            page_url, page_html = fetch_html(
                self.source_name,
                f"{self.base_url}/{page_number}",
            )
            links, _ = parse_html_page(page_html)
            pages.append((page_url, links))

        results = []
        seen: set[str] = set()
        for page_url, links in pages:
            for link in links:
                raw_title = link["text"].strip()
                detail_url = absolute_url(page_url, link["href"])
                match = self.announcement_pattern.search(urlsplit(detail_url).path)
                if not match or not raw_title or detail_url in seen:
                    continue
                parsed = parse_announcement_title(raw_title)
                if not parsed["is_recruitment"]:
                    continue
                seen.add(detail_url)
                results.append(self.normalize_listing({
                    "source_key": "yerel-yonetimler",
                    "source_name": self.source_name,
                    "source_url": self.base_url,
                    "detail_url": detail_url,
                    "external_id": match.group(1),
                    "title": parsed["title"],
                    "institution": parsed["institution"],
                    "city": parsed["city"],
                    "position_title": "",
                    "announcement_date": parsed["announcement_date"],
                    "application_start_date": None,
                    "application_end_date": None,
                    "is_cancellation": parsed["is_cancellation"],
                    "description_html": "",
                    "content_hash": content_hash(parsed["title"]),
                    "metadata": {"list_page": page_url},
                }))
        self.pages_checked = len(pages)
        if not results:
            raise RuntimeError(
                "HTTP 200 yanıtlarında Yerel Yönetimler personel alımı duyurusu bulunamadı."
            )
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        final_url, html = fetch_html(self.source_name, url)
        # Yalnızca duyuru gövdesi alınır; menü, çerez bildirimi ve alt bilgi ilan metni değildir.
        start = html.find("haber-detay-wrapper")
        body_html = html[html.rfind("<", 0, start):] if start != -1 else html
        end = body_html.find("Duyurulara geri d")
        if end != -1:
            body_html = body_html[:end]
        links, text = parse_html_page(body_html)

        attachments = []
        for link in links:
            href = absolute_url(final_url, link["href"])
            path = urlsplit(href).path.casefold()
            if path.endswith((".pdf", ".docx")) and href not in attachments:
                attachments.append(href)
        attachment_error = ""
        for attachment in attachments[:2]:
            from ..documents import fetch_url
            try:
                response = fetch_url(attachment)
                detail = self.document_detail(
                    attachment, response["body"], response["content_type"], "Resmî ilan metni",
                )
            except Exception as error:
                # Belge okunamazsa sayfa metniyle devam edilir; bağlantı kullanıcıya gösterilir.
                attachment_error = str(error)[:300]
                continue
            detail["source_text"] = "\n".join(filter(None, (text, detail["source_text"])))
            detail["detail_url"] = final_url
            return detail

        if len(text) < 100:
            raise RuntimeError(f"Duyuru detayında ayrıştırılabilir metin yok: {final_url}")
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
            "unread_attachments": [
                {"url": attachment, "title": "Resmî ilan metni (ek belge)", "error": attachment_error}
                for attachment in attachments[:2]
            ],
        }
