
import asyncio
from contextlib import contextmanager
import re
from functools import lru_cache
from html.parser import HTMLParser
import time
from urllib.parse import urlsplit

try:  # Playwright yalnızca Kariyer Kapısı taraması için gerekir; yoksa diğer kaynaklar çalışmaya devam eder.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - isteğe bağlı bağımlılık
    PlaywrightTimeoutError = TimeoutError

    def sync_playwright():
        raise RuntimeError(
            "Kariyer Kapısı taraması için Playwright gerekli: "
            "`pip install playwright && playwright install chromium` çalıştırın."
        )


URL = "https://kariyerkapisi.gov.tr/isealim"
API_HOST = "api.kariyerkapisi.gov.tr"
DETAIL_MARKER = "--- Kariyer Kapısı ilan detayları ---"
_TRANSIENT_NAVIGATION_ERRORS = (
    "net::err_name_not_resolved",
    "net::err_timed_out",
    "net::err_connection_reset",
    "net::err_connection_closed",
    "net::err_network_changed",
    "net::err_internet_disconnected",
)


def _is_transient_navigation_error(error):
    message = str(error).casefold()
    status = re.search(r"\bhttp(?:\s+durum\s+kodu|\s+yanıtı)?\s+(\d{3})\b", message)
    return (
        isinstance(error, PlaywrightTimeoutError)
        or any(marker in message for marker in _TRANSIENT_NAVIGATION_ERRORS)
        or bool(status and int(status.group(1)) in {408, 425, 429, 500, 502, 503, 504})
    )


def _watch_api_failures(page):
    failures = []

    def record_request_failure(request):
        if (urlsplit(request.url).hostname or "").casefold() == API_HOST:
            failures.append(f"{request.url}: {request.failure or 'istek başarısız'}")

    def record_response(response):
        if (
            response.status >= 400
            and (urlsplit(response.url).hostname or "").casefold() == API_HOST
        ):
            failures.append(f"{response.url}: HTTP {response.status}")

    page.on("requestfailed", record_request_failure)
    page.on("response", record_response)
    return failures


def _api_failure(failures):
    return RuntimeError(f"Kariyer Kapısı API erişim hatası: {failures[-1]}")


def _goto_with_retries(page, url, *, before_navigation=None, after_navigation=None, **kwargs):
    for attempt in range(3):
        try:
            if before_navigation is not None:
                before_navigation()
            response = page.goto(url, **kwargs)
            if after_navigation is not None:
                after_navigation()
            return response
        except Exception as error:
            if attempt == 2 or not _is_transient_navigation_error(error):
                raise
            time.sleep(1.5 * (attempt + 1))


@contextmanager
def _playwright_event_loop_policy():
    """Playwright needs subprocess support; Uvicorn may install Windows' selector policy."""
    if not hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        yield
        return
    previous = asyncio.get_event_loop_policy()
    if isinstance(previous, asyncio.WindowsSelectorEventLoopPolicy):
        # Playwright's sync API creates its own event loop in this worker thread.
        # A selector loop cannot launch the Playwright driver on Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        yield
    finally:
        if isinstance(previous, asyncio.WindowsSelectorEventLoopPolicy):
            asyncio.set_event_loop_policy(previous)


class _VisibleContent(HTMLParser):
    """Small stdlib HTML text reader used by deterministic parser tests."""

    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "tr", "td", "th", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if data.strip():
            self.text_parts.append(data.strip())


DETAIL_LABELS = {
    "institution": ("Kurum Adı", "Kurum", "İdare"),
    "title": ("İlan Başlığı", "İlan Adı", "Başlık"),
    "position": ("Pozisyon", "Ünvan", "Unvan", "Kadro Unvanı"),
    "quota": ("Kontenjan", "Adet", "Kişi Sayısı"),
    "start_date": ("Başvuru Başlangıç Tarihi", "Başvuru Başlangıcı"),
    "end_date": ("Son Başvuru Tarihi / Saati", "Son Başvuru Tarihi", "Başvuru Bitiş Tarihi", "Başvuru Bitişi"),
    "kpss_score_type": ("KPSS Puan Türü", "KPSS Puan Tipi"),
    "education_requirement": ("Öğrenim Durumu", "Eğitim Seviyesi", "Mezuniyet Seviyesi"),
    "departments": ("Mezun Olunacak Bölümler", "Bölüm Şartı", "Mezuniyet Bölümleri"),
    "qualification_codes": ("Nitelik Kodları", "Nitelik Kodu"),
    "age_requirement": ("Yaş Şartı", "Yaş Sınırı"),
    "experience": ("İş Deneyimi", "Mesleki Tecrübe", "Deneyim Şartı"),
    "certificates": ("Sertifika Şartı", "Sertifikalar", "Belge Şartı"),
    "foreign_languages": ("Yabancı Dil Şartı", "Yabancı Dil", "Dil Şartı"),
    "city": ("Görev Yeri", "Çalışma Yeri", "İl"),
}


def _clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip(" \t:：-–")


@lru_cache(maxsize=256)
def _cached_label_values(text):
    """Read only explicit label/value pairs; never infer a value from context."""
    lines = [cleaned for line in text.splitlines() if (cleaned := _clean_text(line))]
    result = {}
    all_labels = {label.casefold().rstrip(":： ") for labels in DETAIL_LABELS.values() for label in labels}
    for key, labels in DETAIL_LABELS.items():
        for index, line in enumerate(lines):
            for label in labels:
                # Accept only exact standalone labels or explicit label:value pairs.
                # Prefix matching caused false positives such as "İl" in "İlan".
                match = re.match(rf"^{re.escape(label)}\s*[:：]\s*(.*)$", line, re.I)
                if match or line.casefold().rstrip(":： ") == label.casefold():
                    value = _clean_text(match.group(1)) if match else ""
                    if not value and index + 1 < len(lines):
                        candidate = lines[index + 1]
                        candidate_label = candidate.split(":", 1)[0].split("：", 1)[0].casefold().rstrip()
                        if candidate and candidate_label not in all_labels:
                            value = candidate
                    if value:
                        result[key] = value
                        break
            if key in result:
                break

    # A minimum score is saved only when the notice explicitly says "en az".
    score_match = re.search(r"KPSS.{0,40}?en az\s*(\d{2}(?:[.,]\d+)?)", text, re.I | re.S)
    if score_match:
        result["kpss_min_score"] = float(score_match.group(1).replace(",", "."))
    score_type_match = re.search(r"KPSS\s*[- ]?(P\d+)\b", text, re.I)
    if score_type_match:
        result["kpss_score_type"] = score_type_match.group(1).upper()

    # Narrative requirements are copied only when their wording is explicit.
    department_match = re.search(r"(Fakültelerin\s+.*?mezun olmak\.)", text, re.I | re.S)
    if department_match and re.search(r"bölüm", department_match.group(1), re.I):
        result.setdefault("departments", _clean_text(department_match.group(1)))

    experience_lines = [
        line for line in lines
        if re.search(r"en az\s+\d+\s*(?:\([^)]*\)\s*)?yıl(?:lık)?", line, re.I)
        and re.search(r"tecrübe|deneyim|çalışmış olmak", line, re.I)
    ]
    if experience_lines:
        result.setdefault("experience", "\n".join(experience_lines[:5]))

    age_match = re.search(r"(.{0,80}\d+\s*yaş.{0,100}(?:doldurmuş|doldurmamış|üstünde|altında|arasında).{0,80})", text, re.I | re.S)
    if age_match:
        result.setdefault("age_requirement", _clean_text(age_match.group(1)))

    for key, keywords in (("certificates", ("sertifika", "sertifikaları")), ("foreign_languages", ("yabancı dil", "yds", "e-yds"))):
        if key not in result:
            relevant = [line for line in lines if any(word in line.casefold() for word in keywords)]
            if relevant:
                result[key] = "\n".join(relevant[:8])

    return tuple(result.items())


def _label_values(text):
    """Return fresh label values while reusing repeated parsing of the same text."""
    return dict(_cached_label_values(text))


def parse_listing_detail(html, page_url):
    """Extract listing fields from visible HTML text."""
    parser = _VisibleContent()
    parser.feed(html or "")
    return parse_listing_content("\n".join(parser.text_parts))


def parse_listing_content(text):
    """Parse browser-visible text only."""
    fields = _label_values(text)
    stable_lines = []
    for raw_line in text.splitlines():
        line = _clean_text(raw_line)
        if not line:
            continue
        # Countdown widgets change on every visit and would make every sync look updated.
        if re.search(r"kalan\s*(?:süre|zaman)|\b\d+\s*gün\s+kaldı\b|\b\d+\s*gün\s+\d+\s*saat\b|\b\d{1,2}:\d{2}:\d{2}\b", line, re.I):
            continue
        stable_lines.append(line)
    fields["source_text"] = "\n".join(stable_lines)
    return fields


def _block_document_requests(route):
    """Prevent a page from fetching a URL whose path points to a PDF."""
    if urlsplit(route.request.url).path.casefold().endswith(".pdf"):
        route.abort()
    else:
        route.continue_()


def scrape_public_listing_details(listings):
    """Visit Kariyer Kapısı detail pages; one failed page won't stop other listings."""
    urls = [item["url"] for item in listings if item.get("url")]
    outcomes = {}
    with _playwright_event_loop_policy(), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="tr-TR")
            page.route("**/*", _block_document_requests)
            api_failures = _watch_api_failures(page)
            for url in urls:
                try:
                    parsed_url = urlsplit(url)
                    if parsed_url.scheme != "https" or parsed_url.netloc.casefold() != "kariyerkapisi.gov.tr" or not parsed_url.path.casefold().startswith("/ilandetay"):
                        raise ValueError("İlan bağlantısı Kariyer Kapısı detay sayfası değil.")

                    def wait_for_detail_data():
                        try:
                            page.wait_for_load_state("networkidle", timeout=5000)
                        except PlaywrightTimeoutError:
                            pass
                        if api_failures:
                            raise _api_failure(api_failures)

                    response = _goto_with_retries(
                        page,
                        url,
                        before_navigation=api_failures.clear,
                        after_navigation=wait_for_detail_data,
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    if response is None or response.status != 200:
                        raise RuntimeError(f"HTTP durum kodu: {response.status if response else 'yanıt yok'}")
                    visible_text = page.locator("body").inner_text()
                    if not visible_text.strip():
                        raise RuntimeError("İlan detay sayfasında okunabilir metin bulunamadı.")
                    details = parse_listing_content(visible_text)
                    details["attachments"] = page.locator("a[href]").evaluate_all(
                        """anchors => anchors.map(anchor => ({
                            url: anchor.href,
                            title: anchor.innerText.trim()
                        })).filter(item => item.url)"""
                    )
                    outcomes[url] = {"details": details, "error": None}
                except Exception as error:
                    failure = _api_failure(api_failures) if api_failures else error
                    outcomes[url] = {"details": {"source_text": ""}, "error": str(failure)}
        finally:
            browser.close()
    return outcomes


def scrape_public_active_listings():
    """
    Kariyer Kapısı'nın herkese açık aktif ilanlarını toplar.
    Her ilanı bir Python sözlüğü olarak döndürür.
    """

    raw_listings = None
    last_error = None
    with _playwright_event_loop_policy(), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for attempt in range(3):
                page = browser.new_page(locale="tr-TR")
                page.route("**/*", _block_document_requests)
                api_failures = _watch_api_failures(page)
                try:
                    response = page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                    if response is None or response.status != 200:
                        raise RuntimeError(f"Kariyer Kapısı HTTP yanıtı: {response.status if response else 'yanıt yok'}")
                    # Avoid networkidle: the portal keeps analytics/polling requests open.
                    page.wait_for_function("""() => {
                        const body = document.body?.innerText?.toLocaleLowerCase('tr-TR') || '';
                        const empty = body.includes('şu an aktif bir ilan bulunmamaktadır');
                        const hasListing = Array.from(document.querySelectorAll('a[href]'))
                          .some(anchor => /ilandetay/i.test(anchor.getAttribute('href') || ''));
                        return empty || hasListing;
                    }""", timeout=30000)
                    body_text = page.locator("body").inner_text()
                    if api_failures:
                        raise _api_failure(api_failures)
                    if "şu an aktif bir ilan bulunmamaktadır" in body_text.casefold():
                        return []
                    raw_listings = page.locator("a[href]").evaluate_all("""
                        anchors => anchors.filter(anchor => /ilandetay/i.test(anchor.getAttribute('href') || ''))
                          .map(anchor => {
                            const row = anchor.closest('tr') || anchor.parentElement?.parentElement;
                            const columns = row ? Array.from(row.children).map(element => element.innerText.trim()) : [];
                            return {
                              url: anchor.href,
                              institution_department: columns[1] || '',
                              title: columns[2] || anchor.innerText.trim(),
                              deadline: columns[3] || ''
                            };
                          })
                    """)
                    if not raw_listings:
                        raise RuntimeError("Kariyer Kapısı sayfası yüklendi ancak ilan satırları okunamadı.")
                    break
                except Exception as error:
                    last_error = _api_failure(api_failures) if api_failures else error
                    if attempt < 2 and _is_transient_navigation_error(last_error):
                        time.sleep(1.5 * (attempt + 1))
                    else:
                        break
                finally:
                    page.close()
            if raw_listings is None:
                raise RuntimeError(
                    "Kariyer Kapısı ilan listesi 3 denemede yüklenemedi: "
                    f"{last_error or 'bilinmeyen hata'}"
                ) from last_error
        finally:
            browser.close()

    listings = []
    seen_urls = set()
    for item in raw_listings:

        url = item["url"].strip()

        # Aynı ilanı ikinci kez ekleme
        if url in seen_urls:
            continue

        seen_urls.add(url)

        # Kurum ve birim bilgilerini ayır
        institution_lines = [
            line.strip()
            for line in item["institution_department"].splitlines()
            if line.strip()
        ]

        institution = (
            institution_lines[0]
            if institution_lines else ""
        )

        department = (
            institution_lines[1]
            if len(institution_lines) > 1 else ""
        )

        title = item["title"].strip()

        # Tarih ve haftanın gününü koru
        deadline = " ".join(
            item["deadline"].split()
        )

        # Eksik kayıtları dahil etme
        if not institution or not title:
            continue

        listings.append({
            "institution": institution,
            "department": department,
            "title": title,
            "end_date": deadline,
            "url": url,
            "source": "Kariyer Kapısı"
        })

    return listings


if __name__ == "__main__":

    results = scrape_public_active_listings()

    print(f"\nToplam bulunan ilan: {len(results)}")

    for index, listing in enumerate(results, start=1):

        print(f"\n--- İLAN {index} ---")
        print("Kurum:", listing["institution"])
        print("Birim:", listing["department"])
        print("Başlık:", listing["title"])
        print("Bitiş:", listing["end_date"])
        print("Bağlantı:", listing["url"])
