from __future__ import annotations

from datetime import date
import html as html_lib
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from .base import (
    BaseJobSource,
    SourceFetchError,
    absolute_url,
    content_hash,
    external_id,
    fetch_html,
    parse_html_page,
)


def _parse_iskur_deadline(text: str) -> date | None:
    match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return None


def _extract_institution(title: str) -> str:
    cleaned = html_lib.unescape(title).strip()
    match = re.split(
        r"\b(?:sözleşmeli|memur|personel|alım|giriş\s+sınavı|uzman\s+yardımcılığı|müfettiş\s+yardımcılığı|itfaiye\s+eri|zabıta)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if match and match[0].strip():
        inst = match[0].strip()
        if len(inst) >= 4:
            return inst
    return cleaned


class IskurSource(BaseJobSource):
    source_name = "İŞKUR Kamu Memur Alım İlanları"
    base_url = "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari"
    listing_prefix = "/ilanlar/kamu-memur-alim-ilanlari/"

    def fetch_listings(self) -> list[dict[str, Any]]:
        final_url, main_html = fetch_html(self.source_name, self.base_url)
        self.pages_checked = 1
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        # 1. SVG Harita üzerinden ilan bulunan illeri tespit et
        city_pattern = re.compile(
            r'<g\s+id="([^"]+)"[^>]*data-iladi="([^"]+)"[^>]*data-count="([^"]*)"',
            re.IGNORECASE,
        )
        cities = city_pattern.findall(main_html)
        active_cities = [
            (city_id, html_lib.unescape(name).strip(), int(count))
            for city_id, name, count in cities
            if count and count.isdigit() and int(count) > 0
        ]

        if active_cities:
            for city_id, city_name, _ in active_cities:
                city_url = f"{self.base_url}?idId={city_id}&il={city_name}"
                try:
                    _, city_html = fetch_html(self.source_name, city_url)
                    self.pages_checked += 1
                except SourceFetchError:
                    continue

                tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", city_html, re.DOTALL | re.IGNORECASE)
                table_body = tbody.group(1) if tbody else city_html

                rows = re.findall(
                    r"<tr([^>]*class=[\"'][^\"']*clickable-row[^\"']*[\"'][^>]*)>(.*?)</tr>",
                    table_body,
                    re.DOTALL | re.IGNORECASE,
                )
                for tr_attrs, row_inner in rows:
                    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_inner, re.DOTALL | re.IGNORECASE)
                    if len(cells) < 2:
                        continue
                    date_text = " ".join(re.sub(r"<[^>]+>", " ", cells[0]).split())
                    raw_title = " ".join(re.sub(r"<[^>]+>", " ", cells[1]).split())
                    title = html_lib.unescape(raw_title).strip()
                    if not title:
                        continue

                    combined_html = tr_attrs + " " + row_inner
                    file_match = re.search(r'(?:data-file-url|href)=["\']([^"\']+)["\']', combined_html, re.IGNORECASE)
                    file_href = html_lib.unescape(file_match.group(1).strip()) if file_match else ""
                    detail_url = absolute_url(self.base_url, file_href) if file_href else ""

                    if not detail_url or detail_url in seen_urls:
                        continue
                    seen_urls.add(detail_url)

                    deadline = _parse_iskur_deadline(date_text)
                    institution = _extract_institution(title)

                    results.append(self.normalize_listing({
                        "source_key": "iskur",
                        "source_name": self.source_name,
                        "source_url": self.base_url,
                        "detail_url": detail_url,
                        "external_id": external_id(detail_url),
                        "title": title,
                        "institution": institution,
                        "position_title": title,
                        "city": city_name,
                        "announcement_date": None,
                        "application_start_date": None,
                        "application_end_date": deadline,
                        "employment_type": "Kamu Memur / Sözleşmeli",
                        "recruitment_method": "İŞKUR Kamu İlanı",
                        "description_html": f"<p>{title}</p><p>Son Başvuru: {date_text}</p><p>Görev Yeri: {city_name}</p>",
                        "content_hash": content_hash(title, detail_url, date_text),
                        "metadata": {
                            "city_id": city_id,
                            "city_name": city_name,
                            "raw_date": date_text,
                            "attachment_url": detail_url,
                        },
                    }))

        # 2. Eğer haritada şehir bulunamazsa standart HTML bağlantı ayrıştırma fallback'i
        if not results:
            links, _ = parse_html_page(main_html)
            for link in links:
                href = link["href"].strip()
                detail_url = absolute_url(final_url, href)
                path = urlsplit(detail_url).path.casefold()
                title = link["text"].strip()
                if (
                    not path.startswith(self.listing_prefix)
                    or path.rstrip("/") == self.listing_prefix.rstrip("/")
                    or not title
                    or re.search(r"/(?:page|sayfa)/\d+/?$", path)
                ):
                    continue
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                results.append(self.normalize_listing({
                    "source_key": "iskur",
                    "source_name": self.source_name,
                    "source_url": self.base_url,
                    "detail_url": detail_url,
                    "external_id": external_id(detail_url),
                    "title": title,
                    "institution": _extract_institution(title),
                    "position_title": title,
                    "announcement_date": None,
                    "application_start_date": None,
                    "application_end_date": None,
                    "description_html": "",
                    "content_hash": content_hash(title),
                    "metadata": {"list_page": final_url},
                }))

        if not results:
            raise RuntimeError(
                "İŞKUR yanıtı HTTP 200 olsa da kamu ilanı detay bağlantısı bulunamadı."
            )
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        path = urlsplit(url).path.casefold()
        if path.endswith(".pdf"):
            from ..documents import fetch_url, parse_document
            try:
                doc_res = fetch_url(url, max_bytes=10 * 1024 * 1024)
                if doc_res.get("not_modified"):
                    return {"source_text": "", "content_hash": "", "detail_url": url, "positions": []}
                parsed = parse_document(url, doc_res["body"], doc_res["content_type"])
                text = parsed.get("text") or ""
                return {
                    "source_text": text,
                    "content_hash": content_hash(text),
                    "detail_url": url,
                    "positions": parsed.get("positions") or [],
                }
            except Exception as error:
                raise SourceFetchError(
                    self.source_name,
                    url,
                    f"İŞKUR ek PDF belgesi ayrıştırılamadı: {error}",
                ) from error

        final_url, html = fetch_html(self.source_name, url)
        _, text = parse_html_page(html)
        if len(text) < 80:
            raise SourceFetchError(
                self.source_name,
                final_url,
                "İŞKUR ilan detayında ayrıştırılabilir metin yok.",
            )
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
        }
