"""Kaynak erişim tanılaması: `python -m backend.diagnose [--json]`.

Her resmî kaynağın adresi için DNS, TCP, TLS ve HTTP katmanlarını ayrı ayrı ölçer; böylece bir
tarama hatasının nedeni (alan adı çözülmüyor / bağlantı kurulmuyor / sertifika / erişim reddi /
sayfa içeriği) tahminle değil ölçümle söylenir. Hiçbir şeyi değiştirmez, veritabanına yazmaz.
Uygulamanın çalıştığı her ortamda (yerel bilgisayar, Render, GitHub Actions) aynı komutla çalışır.
"""

from __future__ import annotations

import json
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit

import requests

from . import tls
from .sources.base import DEFAULT_HEADERS

TARGETS = [
    ("SBB Kamu İlanları", "https://kamuilan.sbb.gov.tr/"),
    ("Kariyer Kapısı (sayfa)", "https://kariyerkapisi.gov.tr/isealim"),
    ("Kariyer Kapısı (ilan servisi)", "https://api.kariyerkapisi.gov.tr/"),
    ("Yerel Yönetimler", "https://yerelyonetimler.csb.gov.tr/duyurular"),
    ("Yerel Yönetimler (ek belgeler)", "https://webdosya.csb.gov.tr/"),
    ("İŞKUR", "https://www.iskur.gov.tr/ilanlar/kamu-memur-alim-ilanlari"),
    ("İlan.gov.tr", "https://www.ilan.gov.tr/ilan/kategori/44/kamu-personel-alim-ve-sinavlari"),
    ("ÖSYM", "https://www.osym.gov.tr/"),
    ("MEB YYEGM (YLSY)", "https://yyegm.meb.gov.tr/meb_iys_dosyalar/xml/rss_duyurular.xml"),
]
CONNECT_TIMEOUT = 12


def _timed(function):
    started = time.monotonic()
    try:
        return function(), None, round(time.monotonic() - started, 2)
    except Exception as error:  # tanılama: her hata türü raporlanır
        return None, f"{type(error).__name__}: {str(error)[:160]}", round(time.monotonic() - started, 2)


def probe(name: str, url: str) -> dict:
    host = urlsplit(url).hostname or ""
    result: dict = {"name": name, "url": url, "host": host, "verdict": ""}

    addresses, error, seconds = _timed(lambda: sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}))
    result["dns"] = {"ok": error is None, "addresses": addresses or [], "error": error, "seconds": seconds}
    if error:
        result["verdict"] = "DNS: alan adı bu ortamdan çözülemiyor"
        return result

    def connect():
        connection = socket.create_connection((host, 443), timeout=CONNECT_TIMEOUT)
        connection.close()
        return True

    _, error, seconds = _timed(connect)
    result["tcp"] = {"ok": error is None, "error": error, "seconds": seconds}
    if error:
        result["verdict"] = "TCP: sunucu bu ortamdan gelen bağlantıyı kabul etmiyor (zaman aşımı / ret)"
        return result

    def handshake():
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=CONNECT_TIMEOUT) as raw:
            with context.wrap_socket(raw, server_hostname=host) as secured:
                return secured.version()

    version, error, seconds = _timed(handshake)
    result["tls"] = {"ok": error is None, "version": version, "error": error, "seconds": seconds}
    # Eksik ara sertifika burada hata verir; uygulama bunu doğrulamayı kapatmadan tamamlar (backend/tls.py).

    def fetch():
        response = tls.get(url, headers=DEFAULT_HEADERS, timeout=(CONNECT_TIMEOUT, 30), allow_redirects=True)
        body = response.content[:200_000]
        return {
            "status": response.status_code, "final_url": response.url,
            "content_type": response.headers.get("content-type", ""), "bytes": len(response.content),
            "server": response.headers.get("server", ""), "retry_after": response.headers.get("retry-after", ""),
            "blocked_marker": any(marker in body.lower() for marker in (b"request rejected", b"access denied", b"erisiminiz engellenmistir", "erişiminiz engellenmiştir".encode())),
        }

    http, error, seconds = _timed(fetch)
    result["http"] = {"ok": error is None and http is not None and http["status"] == 200, "error": error, "seconds": seconds, **(http or {})}
    if error:
        kind = "TLS" if "SSL" in error else "zaman aşımı" if "Timeout" in error else "bağlantı"
        result["verdict"] = f"HTTP isteği tamamlanamadı ({kind})"
    elif http["status"] in (401, 403):
        result["verdict"] = f"HTTP {http['status']}: sunucu bu ortamdan gelen isteği reddediyor (erişim kuralı)"
    elif http["status"] == 429:
        result["verdict"] = "HTTP 429: istek sınırı"
    elif http["status"] >= 500:
        result["verdict"] = f"HTTP {http['status']}: kaynak sunucusunda hata"
    elif http["status"] != 200:
        # Servis adresinin kök yolu yoksa 404 döner; sunucuya ulaşıldığı için erişim vardır.
        result["verdict"] = "Erişilebilir (kök adres yok)" if http["status"] == 404 and urlsplit(url).path in ("", "/") else f"HTTP {http['status']}"
    elif http["blocked_marker"]:
        result["verdict"] = "HTTP 200 ama içerik bir erişim engeli sayfası"
    else:
        result["verdict"] = "Erişilebilir"
    return result


def outbound_location() -> dict:
    """Bu ortamın dış dünyaya hangi ülkeden çıktığını gösterir (yalnızca tanılama çıktısı için)."""
    try:
        text = requests.get("https://www.cloudflare.com/cdn-cgi/trace", timeout=8).text
        fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        return {"country": fields.get("loc", "?"), "colo": fields.get("colo", "?")}
    except Exception:
        return {"country": "?", "colo": "?"}


def browser_check() -> dict:
    """Kariyer Kapısı ve İlan.gov.tr için gereken tarayıcının (Chromium) bu ortamda açılıp açılmadığı."""
    try:
        from .kariyerkapisi import _playwright_event_loop_policy, sync_playwright

        with _playwright_event_loop_policy(), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                version = browser.version
            finally:
                browser.close()
        return {"ok": True, "detail": f"Chromium {version}"}
    except Exception as error:
        return {"ok": False, "detail": f"{type(error).__name__}: {str(error).splitlines()[0][:200]}"}


def run() -> dict:
    from . import config, database

    return {
        "location": outbound_location(), "origin": config.scan_origin(), "storage": database.storage_status(),
        "browser": browser_check(), "targets": [probe(name, url) for name, url in TARGETS],
    }


def markdown(report: dict) -> str:
    lines = [f"Ortam: {report.get('origin', '?')} · çıkış ülkesi: **{report['location']['country']}** ({report['location']['colo']})",
             f"Tarayıcı (Chromium): {'çalışıyor' if report['browser']['ok'] else 'ÇALIŞMIYOR'} — {report['browser']['detail']}",
             f"Veritabanı: {report['storage']['backend']} · kalıcı: {'evet' if report['storage']['durable'] else 'HAYIR'}", "",
             "| Kaynak | DNS | TCP | TLS | HTTP | Sonuç |", "|---|---|---|---|---|---|"]

    def cell(part: dict | None, ok_text: str = "tamam") -> str:
        if part is None:
            return "—"
        return f"{ok_text} ({part['seconds']} sn)" if part["ok"] else f"HATA ({part['seconds']} sn)"

    for item in report["targets"]:
        http = item.get("http")
        http_text = "—" if http is None else (str(http.get("status") or "yanıt yok") + f" ({http['seconds']} sn)")
        lines.append(f"| {item['name']} | {cell(item.get('dns'))} | {cell(item.get('tcp'))} | {cell(item.get('tls'))} | {http_text} | {item['verdict']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    outcome = run()
    print(json.dumps(outcome, ensure_ascii=False, indent=2) if "--json" in sys.argv else markdown(outcome))
