from __future__ import annotations

from typing import Any

from ..kariyerkapisi import scrape_public_active_listings, scrape_public_listing_details
from .base import BaseJobSource, content_hash, external_id


class KariyerKapisiSource(BaseJobSource):
    source_name = "Kariyer Kapısı"
    base_url = "https://kariyerkapisi.gov.tr/isealim"

    def fetch_listings(self) -> list[dict[str, Any]]:
        listings = scrape_public_active_listings()
        self.pages_checked = 1
        results = []
        for item in listings:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            results.append(self.normalize_listing({
                "source_key": "kariyer-kapisi",
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": url,
                "external_id": external_id(url),
                "title": title,
                "institution": item.get("institution") or "",
                "position_title": "",
                "application_end_date": item.get("end_date"),
                "description_html": "",
                "content_hash": content_hash(title, str(item.get("end_date") or "")),
                "metadata": item,
            }))
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        outcome = scrape_public_listing_details([{"url": url}]).get(url)
        if not outcome:
            raise RuntimeError("Kariyer Kapısı detay sayfası için sonuç dönmedi.")
        if outcome.get("error"):
            raise RuntimeError(str(outcome["error"]))
        details = outcome.get("details") or {}
        text = str(details.get("source_text") or "").strip()
        if len(text) < 80:
            raise RuntimeError("Kariyer Kapısı detay sayfasında ayrıştırılabilir metin yok.")
        return {
            **details,
            "detail_url": url,
            "content_hash": content_hash(text),
            "attachments": details.get("attachments") or [],
        }
