
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


URL = "https://kariyerkapisi.gov.tr/isealim"
DETAIL_MARKER = "--- Kariyer Kapısı ilan detayları ---"


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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="tr-TR")
            page.route("**/*", _block_document_requests)
            for url in urls:
                try:
                    parsed_url = urlsplit(url)
                    if parsed_url.scheme != "https" or parsed_url.netloc.casefold() != "kariyerkapisi.gov.tr" or not parsed_url.path.casefold().startswith("/ilandetay"):
                        raise ValueError("İlan bağlantısı Kariyer Kapısı detay sayfası değil.")
                    response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    if response is None or response.status != 200:
                        raise RuntimeError(f"HTTP durum kodu: {response.status if response else 'yanıt yok'}")
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except PlaywrightTimeoutError:
                        # Some pages keep analytics connections open; visible content is still usable.
                        pass
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
                    outcomes[url] = {"details": {"source_text": ""}, "error": str(error)}
        finally:
            browser.close()
    return outcomes


def scrape_public_active_listings():
    """
    Kariyer Kapısı'nın herkese açık aktif ilanlarını toplar.
    Her ilanı bir Python sözlüğü olarak döndürür.
    """

    listings = []
    seen_urls = set()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        try:
            page = browser.new_page(locale="tr-TR")
            page.route("**/*", _block_document_requests)

            response = page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response is None or response.status != 200:
                raise RuntimeError(
                    "Kariyer Kapısı sayfasına erişilemedi."
                )

            body_text = page.locator("body").inner_text()
            if "şu an aktif bir ilan bulunmamaktadır" in body_text.casefold():
                return []

            try:
                page.wait_for_selector('a[href*="IlanDetay"]', timeout=20000)
            except PlaywrightTimeoutError as error:
                raise RuntimeError(
                    "Kariyer Kapısı ilan bağlantısı yüklenmedi; sayfa boş veya erişim kontrollü olabilir."
                ) from error

            # Her ilan bağlantısının bulunduğu satırı oku
            raw_listings = page.locator(
                'a[href*="IlanDetay"]'
            ).evaluate_all("""
                anchors => anchors.map(anchor => {

                    const row = anchor.parentElement.parentElement;

                    const columns = Array.from(row.children).map(
                        element => element.innerText.trim()
                    );

                    return {
                        url: anchor.href,
                        institution_department: columns[1] || "",
                        title: columns[2] || "",
                        deadline: columns[3] || ""
                    };
                })
            """)

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

                listing = {
                    "institution": institution,
                    "department": department,
                    "title": title,
                    "end_date": deadline,
                    "url": url,
                    "source": "Kariyer Kapısı"
                }

                listings.append(listing)

        finally:
            browser.close()

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
