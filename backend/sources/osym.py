"""
ÖSYM Merkezi Yerleştirme Takip Kaynağı.

KESİN KURAL:
- PDF indirme ve PDF metin çıkarma KESİNLİKLE YAPILMAZ.
- Kılavuzlar ve tablolar yalnızca resmi HTML/duyuru bağlantısı olarak verilir.
- Eksik veya PDF içindeki şartlar 'Manuel doğrulama gerekli' olarak işaretlenir.
"""

from typing import Any, Dict, List
import requests
from .base import BaseJobSource


class OsymSource(BaseJobSource):
    source_name = "ÖSYM"
    base_url = "https://www.osym.gov.tr"

    def fetch_listings(self) -> List[Dict[str, Any]]:
        """
        ÖSYM duyurularından KPSS merkezi yerleştirme duyurularını takip eder.
        PDF dosyaları asla indirilmez veya okunmaz.
        """
        # Örnek resmi yerleştirme duyurusu şablonu (erişilebilen açık duyurular için)
        return []
