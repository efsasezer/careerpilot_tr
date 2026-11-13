"""Genişletilebilir kamu ilanı kaynak mimarisi.

KESİN KURAL: PDF İNDİRME VE OKUMA YOKTUR.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List


class BaseJobSource(ABC):
    """Tüm ilan kaynakları için ortak arayüz."""

    source_name: str = ""
    base_url: str = ""

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
        payload.setdefault("last_checked_at", datetime.utcnow().isoformat())
        payload.setdefault("content_hash", "")
        payload.setdefault("metadata", {})
        return payload

    @abstractmethod
    def fetch_listings(self) -> List[Dict[str, Any]]:
        """İlanları çeker ve standart alanlar içeren sözlük listesi döndürür."""
