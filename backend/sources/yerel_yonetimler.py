from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any, Dict, List

import requests

from .base import BaseJobSource


class YerelYonetimlerSource(BaseJobSource):
    source_name = "Yerel Yönetimler Genel Müdürlüğü"
    base_url = "https://yerelyonetimler.csb.gov.tr/duyurular"

    def fetch_listings(self) -> List[Dict[str, Any]]:
        try:
            response = requests.get(self.base_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except Exception:
            return []

        html = response.text
        anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.I | re.S)
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for href, label_html in anchors:
            if not href or "javascript:" in href.lower():
                continue
            title = self.strip_tags(label_html)
            if not title:
                continue
            lowered = title.casefold()
            if not any(keyword in lowered for keyword in ["memur", "sözleşmeli", "sozlesmeli", "zabıta", "itfaiye", "belediye", "personel", "personel alımı", "alım"]):
                continue
            detail_url = href if href.startswith("http") else f"https://yerelyonetimler.csb.gov.tr{href if href.startswith('/') else '/' + href}"
            payload = self.normalize_listing({
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": detail_url,
                "title": title,
                "institution": self.extract_institution(title),
                "position_title": title,
                "city": self.extract_city_from_text(title),
                "quota": None,
                "announcement_date": self._extract_date(title),
                "application_start_date": None,
                "application_end_date": self._extract_date(title),
                "employment_type": "Yerel yönetim personeli",
                "description_html": f"<p>{title}</p>",
                "source_status": "ok" if response.status_code == 200 else "error",
                "first_seen_at": None,
                "last_checked_at": None,
                "content_hash": hashlib.sha1((title + detail_url).encode("utf-8")).hexdigest(),
            })
            key = payload["detail_url"] or payload["title"]
            if key not in seen:
                seen.add(key)
                results.append(payload)
        return results

    @staticmethod
    def strip_tags(value: str) -> str:
        text = unescape(value or "")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" -:|•")

    @staticmethod
    def extract_institution(title: str) -> str:
        for keyword in ["belediye", "ilçe", "büyükşehir", "mahalli idare", "il müdürlüğü", "valiliği"]:
            if keyword in title.casefold():
                return title.strip()
        return "Yerel Yönetim"

    @staticmethod
    def extract_city_from_text(text: str) -> str | None:
        for city in ["ankara", "istanbul", "izmir", "trabzon", "konya", "adana", "bursa", "antalya", "gaziantep", "samsun", "van", "malatya"]:
            if city in text.casefold():
                return city.title()
        return None

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
        if match:
            return match.group(1)
        return None
