"""Uygulamanın saati: her ortamda Türkiye saati.

Sunucular (Render, GitHub Actions) UTC çalışır; ilan tarihleri ve son başvuru günleri ise Türkiye
saatine göredir. `date.today()` kullanılsaydı gece 00:00-03:00 arasında "bugün" bir gün geride kalır,
"bugün son gün" hatırlatması yanlış güne düşerdi. Bütün zaman damgaları saat dilimi bilgisi
taşımayan Türkiye saati olarak saklanır; böylece farklı ortamlardaki tarayıcılar aynı saati kullanır.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Istanbul")


def now() -> datetime:
    return datetime.now(TIMEZONE).replace(tzinfo=None)


def today() -> date:
    return now().date()
