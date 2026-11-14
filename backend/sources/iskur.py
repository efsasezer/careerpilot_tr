from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .base import (
    BaseJobSource,
    absolute_url,
    content_hash,
    external_id,
    fetch_html,
    parse_html_page,
)


class IskurSource(BaseJobSource):
    source_name = "İŞKUR Kamu Memur Alım İlanları"
    base_url = "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari"
    listing_prefix = "/ilanlar/kamu-memur-alim-ilanlari/"

    def fetch_listings(self) -> list[dict[str, Any]]:
        final_url, html = fetch_html(self.source_name, self.base_url)
        links, _ = parse_html_page(html)
        results = []
        seen: set[str] = set()
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
            if detail_url in seen:
                continue
            seen.add(detail_url)
            results.append(self.normalize_listing({
                "source_key": "iskur",
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": detail_url,
                "external_id": external_id(detail_url),
                "title": title,
                "institution": "",
                "position_title": "",
                "announcement_date": None,
                "application_start_date": None,
                "application_end_date": None,
                "description_html": "",
                "content_hash": content_hash(title),
                "metadata": {"list_page": final_url},
            }))
        self.pages_checked = 1
        if not results:
            raise RuntimeError(
                "İŞKUR yanıtı HTTP 200 olsa da kamu ilanı detay bağlantısı bulunamadı."
            )
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        final_url, html = fetch_html(self.source_name, url)
        _, text = parse_html_page(html)
        if len(text) < 100:
            raise RuntimeError(f"İŞKUR ilan detayında ayrıştırılabilir metin yok: {final_url}")
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
        }
