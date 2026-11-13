from playwright.sync_api import sync_playwright

URL = "https://kariyerkapisi.gov.tr/isealim"


def inspect_page():
    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page(locale="tr-TR")

        print("Kariyer Kapısı açılıyor...")

        response = page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        # JavaScript ile yüklenen içerikleri bekle
        page.wait_for_timeout(7000)

        print("\n--- SAYFA BİLGİLERİ ---")

        print("HTTP Status:", response.status if response else "Bilinmiyor")
        print("Sayfa başlığı:", page.title())
        print("Açılan adres:", page.url)

        # Sayfada görünen metinleri al
        print("\n--- SAYFA İÇERİĞİ ---")

        try:
            content = page.locator("body").inner_text()

            print(content[:8000])

        except Exception as error:
            print("İçerik okunamadı:", error)

        # Sayfadaki bağlantıları bul
        print("\n--- SAYFA BAĞLANTILARI ---")

        links = page.locator("a").evaluate_all("""
            elements => elements.map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href
            })).filter(x => x.text || x.href)
        """)

        for link in links[:40]:
            print(link)

            print("\n--- İLAN KOLONLARI ---")

        detail_links = page.locator(
            'a[href*="IlanDetay"]'
        )

        for index in range(min(detail_links.count(), 3)):

            link = detail_links.nth(index)

            columns = link.evaluate("""
                a => {
                    const row = a.parentElement.parentElement;

                    return Array.from(row.children).map(
                        (element, index) => ({
                            index: index,
                            className: element.className,
                            text: element.innerText.trim()
                        })
                    );
                }
            """)

            print(f"\\nİLAN {index + 1}")

            for column in columns:
                print(column)
        

        browser.close()


if __name__ == "__main__":
    inspect_page()