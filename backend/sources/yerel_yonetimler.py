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


class YerelYonetimlerSource(BaseJobSource):
    source_name = "Yerel Yönetimler Genel Müdürlüğü"
    base_url = "https://yerelyonetimler.csb.gov.tr/duyurular"
    announcement_pattern = re.compile(r"-duyuru-(\d+)(?:/|$)", re.I)
    page_pattern = re.compile(r"/duyurular/(\d+)/?$", re.I)

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
        for page_number in range(2, last_page + 1):
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
                title = link["text"].strip()
                detail_url = absolute_url(page_url, link["href"])
                match = self.announcement_pattern.search(urlsplit(detail_url).path)
                if not match or not title or detail_url in seen:
                    continue
                seen.add(detail_url)
                results.append(self.normalize_listing({
                    "source_key": "yerel-yonetimler",
                    "source_name": self.source_name,
                    "source_url": self.base_url,
                    "detail_url": detail_url,
                    "external_id": match.group(1),
                    "title": title,
                    "institution": "",
                    "position_title": "",
                    "announcement_date": None,
                    "application_start_date": None,
                    "application_end_date": None,
                    "description_html": "",
                    "content_hash": content_hash(title),
                    "metadata": {"list_page": page_url},
                }))
        self.pages_checked = len(pages)
        if not results:
            raise RuntimeError(
                "HTTP 200 yanıtlarında Yerel Yönetimler duyuru bağlantısı bulunamadı."
            )
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        final_url, html = fetch_html(self.source_name, url)
        _, text = parse_html_page(html)
        if len(text) < 100:
            raise RuntimeError(f"Duyuru detayında ayrıştırılabilir metin yok: {final_url}")
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
        }
