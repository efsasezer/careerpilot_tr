from __future__ import annotations

import hashlib
import re
from html import unescape
from typing import Any, Dict, List

import requests

from .base import BaseJobSource


class SBBSource(BaseJobSource):
    source_name = "SBB Kamu İlanları"
    base_url = "https://kamuilan.sbb.gov.tr/"

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
            title = self.strip_tags(label_html) or self.extract_title_from_href(href)
            if not title:
                continue
            lowered = title.casefold()
            if not any(keyword in lowered for keyword in ["personel", "memur", "işçi", "eleman", "muhendis", "tekniker", "sözleşmeli", "sözlesmeli"]):
                continue

            detail_url = href if href.startswith("http") else f"{self.base_url.rstrip('/')}/{href.lstrip('/')}"
            payload = self.normalize_listing({
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": detail_url,
                "title": title,
                "institution": "SBB",
                "position_title": title,
                "city": self.extract_city_from_text(title),
                "quota": None,
                "announcement_date": self._extract_date(html),
                "application_start_date": None,
                "application_end_date": self._extract_date(html),
                "employment_type": "Kamu personeli",
                "description_html": self._build_description(html, title),
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
    def extract_title_from_href(href: str) -> str:
        candidate = href.split("/")[-1].replace("-", " ")
        return candidate.replace("%20", " ").strip() or ""

    @staticmethod
    def extract_city_from_text(text: str) -> str | None:
        city_matches = [
            "ankara", "istanbul", "izmir", "bursa", "adana", "konya", "trabzon", "erzurum", "antalya",
            "diyarbakir", "gaziantep", "kayseri", "samsun", "eskişehir", "sakarya", "mugla"
        ]
        lowered = text.casefold()
        for city in city_matches:
            if city in lowered:
                return city.title()
        return None

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _build_description(html_text: str, title: str) -> str:
        snippet = re.sub(r"\s+", " ", html_text)
        if title:
            return f"<p>{title}</p><p>{snippet[:400]}</p>"
        return snippet[:400]
