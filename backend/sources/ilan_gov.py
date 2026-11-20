"""İlan.gov.tr (Basın İlan Kurumu) – Kamu Personel Alım ve Sınavları kategorisi.

Site tarayıcıda çizilen bir uygulama olduğu için sayfalar Playwright ile okunur.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

from ..kariyerkapisi import (
    PlaywrightTimeoutError,
    _playwright_event_loop_policy,
    sync_playwright,
)
from .base import BaseJobSource, content_hash

_LISTING_PATH = re.compile(r"/ilan/(\d+)/")
_CARDS_SCRIPT = """anchors => anchors
    .filter(a => /\\/ilan\\/\\d+\\//.test(a.pathname))
    .map(a => ({ href: a.href, text: a.innerText }))"""


def parse_card(href: str, text: str) -> dict[str, Any] | None:
    """Liste kartı: kurum / başlık / ilan numarası (DPB…) / şehir satırlarından oluşur."""
    match = _LISTING_PATH.search(href)
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    if not match or len(lines) < 2:
        return None
    number = next((line for line in lines if re.fullmatch(r"[A-ZİÇĞÖŞÜ]{2,5}\d{4,}", line)), "")
    rest = [line for line in lines[2:] if line != number]
    city = rest[-1].title() if rest and len(rest[-1]) <= 40 else ""
    return {
        "external_id": match.group(1),
        "institution": lines[0],
        "title": lines[1],
        "listing_number": number,
        "city": city,
    }


def extract_notice_text(body_text: str) -> tuple[str, dict[str, str]]:
    """Detay sayfasının görünen metninden ilan metnini ve "İlan Bilgileri" alanlarını ayırır."""
    text = (body_text or "").replace("\xa0", " ")
    start = re.search(r"^İlan Metni.*$", text, re.M)
    if start:
        text = text[start.end():]
    info: dict[str, str] = {}
    end = re.search(r"^İlan Bilgileri\s*$", text, re.M)
    if end:
        tail = [line.strip() for line in text[end.end():].splitlines() if line.strip()]
        text = text[:end.start()]
        labels = {"İlan Sahibi": "owner", "İlan Numarası": "number", "Şehir": "city", "Resmî Gazete Yayım Tarihi": "published"}
        for index, line in enumerate(tail[:-1]):
            if line in labels:
                info[labels[line]] = tail[index + 1]
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line), info


class IlanGovSource(BaseJobSource):
    source_name = "İlan.gov.tr"
    base_url = "https://www.ilan.gov.tr/ilan/kategori/44/kamu-personel-alim-ve-sinavlari"
    max_pages = 15

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def _open(self):
        if self._page is None:
            with _playwright_event_loop_policy():
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=True)
                self._page = self._browser.new_page(locale="tr-TR")
        return self._page

    def close(self) -> None:
        for resource in (self._browser, self._playwright):
            try:
                if resource is not None:
                    resource.close() if resource is self._browser else resource.stop()
            except Exception:
                pass
        self._playwright = self._browser = self._page = None

    def fetch_listings(self) -> list[dict[str, Any]]:
        page = self._open()
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        self.pages_checked = 0
        for number in range(1, self.max_pages + 1):
            url = self.base_url if number == 1 else f"{self.base_url}?currentPage={number}"
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if response is None or response.status != 200:
                raise RuntimeError(f"İlan.gov.tr liste sayfası alınamadı (sayfa {number}).")
            try:
                page.wait_for_function(
                    "() => [...document.querySelectorAll('a[href*=\"/ilan/\"]')].some(a => /\\/ilan\\/\\d+\\//.test(a.pathname))",
                    timeout=20000,
                )
            except PlaywrightTimeoutError:
                if number == 1:
                    raise RuntimeError("İlan.gov.tr liste sayfasında ilan bağlantısı yüklenmedi.")
                break
            page.wait_for_timeout(800)
            self.pages_checked += 1
            cards = page.locator('a[href*="/ilan/"]').evaluate_all(_CARDS_SCRIPT)
            new_on_page = 0
            for card in cards:
                parsed = parse_card(card["href"], card["text"])
                if not parsed or parsed["external_id"] in seen:
                    continue
                seen.add(parsed["external_id"])
                new_on_page += 1
                detail_url = card["href"].split("?")[0]
                results.append(self.normalize_listing({
                    "source_key": "ilan-gov",
                    "source_name": self.source_name,
                    "source_url": self.base_url,
                    "detail_url": detail_url,
                    "external_id": parsed["external_id"],
                    "title": parsed["title"],
                    "institution": parsed["institution"],
                    "city": parsed["city"],
                    "content_hash": content_hash(parsed["title"], parsed["institution"], parsed["listing_number"]),
                    "metadata": {"listing_number": parsed["listing_number"], "list_page": url},
                }))
            if new_on_page == 0:
                break  # son sayfadan sonra aynı kayıtlar döner
        if not results:
            raise RuntimeError("İlan.gov.tr yanıt verdi ancak personel alım ilanı bulunamadı.")
        return results

    def fetch_detail(self, url: str) -> dict[str, Any]:
        page = self._open()
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is None or response.status != 200:
            raise RuntimeError(f"İlan sayfası alınamadı (HTTP {response.status if response else 'yanıt yok'}).")
        try:
            page.wait_for_selector("text=İlan Numarası", timeout=25000)
        except PlaywrightTimeoutError as error:
            raise RuntimeError("İlan metni yüklenmedi.") from error
        page.wait_for_timeout(500)
        text, info = extract_notice_text(page.locator("body").inner_text())
        if len(text) < 80:
            raise RuntimeError("İlan sayfasında ayrıştırılabilir metin yok.")
        detail: dict[str, Any] = {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": url,
            "institution": info.get("owner", ""),
            "city": info.get("city", "").title(),
            "announcement_date": info.get("published", ""),
        }
        # İlan metnindeki kadro tablolarını pozisyonlara ayır.
        try:
            from ..documents import parse_document

            html = page.locator(".single-ilan-content .tab-content").first.inner_html(timeout=3000)
            body = f"<html><body>{html}</body></html>".encode("utf-8")
            parsed = parse_document("https://www.ilan.gov.tr/ilan.html", body, "text/html")
            if parsed["positions"]:
                parsed["links"] = []
                detail["document"] = {
                    "url": url, "title": "İlan metni (İlan.gov.tr)", "content_type": "text/html",
                    "body_hash": sha256(body).hexdigest(), "parsed": parsed,
                }
        except Exception:
            pass  # tablo çıkarılamazsa düz metinle devam edilir
        return detail
