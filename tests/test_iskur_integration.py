from datetime import date

import pytest

from backend.sources import iskur
from backend.sources.base import SourceFetchError


MOCK_MAP_HTML = """
<html>
<body>
<div id="svg-turkiye-haritasi">
    <g id="ankara" data-iladi="ANKARA" data-plakakodu="06" data-alankodu="312" data-count="3">
        <path d="M..."/>
    </g>
    <g id="istanbul" data-iladi="İSTANBUL" data-plakakodu="34" data-alankodu="212" data-count="5">
        <path d="M..."/>
    </g>
    <g id="izmir" data-iladi="İZMİR" data-plakakodu="35" data-alankodu="232" data-count="0">
        <path d="M..."/>
    </g>
</div>
</body>
</html>
"""

MOCK_CITY_HTML = """
<html>
<body>
<table class="table">
    <tr class="clickable-row" data-file-url="/medya/12345/ankara-memur-alim.pdf">
        <td>01.12.2026</td>
        <td>Ankara Büyükşehir Belediyesi Memur Alımı</td>
    </tr>
    <tr class="clickable-row">
        <td>15/12/2026</td>
        <td><a href="/medya/67890/cankaya-zabita.pdf">Çankaya Belediyesi Zabıta Alımı</a></td>
    </tr>
</table>
</body>
</html>
"""


def test_iskur_discovers_active_cities_and_table_rows(monkeypatch):
    source = iskur.IskurSource()

    def mock_fetch(name, url):
        if "idId=" in url:
            return url, MOCK_CITY_HTML
        return url, MOCK_MAP_HTML

    monkeypatch.setattr(iskur, "fetch_html", mock_fetch)

    listings = source.fetch_listings()

    assert len(listings) >= 2
    titles = [item["title"] for item in listings]
    assert "Ankara Büyükşehir Belediyesi Memur Alımı" in titles
    assert "Çankaya Belediyesi Zabıta Alımı" in titles
    assert [item["application_end_date"] for item in listings] == [
        date(2026, 12, 1),
        date(2026, 12, 15),
    ]

    for item in listings:
        assert item["source_key"] == "iskur"
        assert item["detail_url"].startswith("https://www.iskur.gov.tr/medya/")
        assert item["detail_url"].endswith(".pdf")
        assert item["city"] in ["ANKARA", "İSTANBUL"]


def test_iskur_fetch_detail_for_pdf(monkeypatch):
    from backend import documents
    source = iskur.IskurSource()

    pdf_bytes = b"%PDF-1.4 mock pdf content"
    monkeypatch.setattr(
        documents,
        "fetch_url",
        lambda url, **kwargs: {"body": pdf_bytes, "content_type": "application/pdf", "not_modified": False},
    )
    monkeypatch.setattr(
        documents,
        "parse_document",
        lambda url, body, ct: {"text": "Örnek Memur Alımı Şartları", "positions": []},
    )

    detail = source.fetch_detail("https://www.iskur.gov.tr/medya/12345/test.pdf")
    assert detail["detail_url"] == "https://www.iskur.gov.tr/medya/12345/test.pdf"
    assert "Örnek Memur Alımı Şartları" in detail["source_text"]


def test_iskur_scanned_pdf_uses_ocr_when_text_extraction_fails(monkeypatch):
    from backend import documents, ocr

    source = iskur.IskurSource()
    monkeypatch.setattr(
        documents,
        "fetch_url",
        lambda _url, **_kwargs: {
            "body": b"%PDF-1.4 scanned",
            "content_type": "application/pdf",
            "not_modified": False,
        },
    )

    def no_text_layer(_url, _body, _content_type):
        raise documents.DocumentParseError("PDF metin katmanı boş.")

    monkeypatch.setattr(documents, "parse_document", no_text_layer)
    monkeypatch.setattr(
        ocr,
        "ocr_pdf",
        lambda _body: {
            "text": "Başvurular 09/12/2026 - 11/12/2026 tarihleri arasında.",
            "confidence": 0.94,
            "pages": 1,
            "truncated": False,
        },
    )

    detail = source.fetch_detail("https://www.iskur.gov.tr/medya/12345/scanned.pdf")

    assert "09/12/2026 - 11/12/2026" in detail["source_text"]
    assert detail["document"]["parsed"]["ocr_confidence"] == 0.94
    assert detail["document"]["parsed"]["partially_read"] is True


def test_iskur_surfaces_reason_when_scanned_pdf_cannot_be_ocr_read(monkeypatch):
    from backend import documents, ocr

    source = iskur.IskurSource()
    monkeypatch.setattr(
        documents,
        "fetch_url",
        lambda _url, **_kwargs: {
            "body": b"%PDF-1.4 scanned",
            "content_type": "application/pdf",
            "not_modified": False,
        },
    )
    monkeypatch.setattr(
        documents,
        "parse_document",
        lambda *_args: (_ for _ in ()).throw(
            documents.DocumentParseError("PDF metin katmanı boş.")
        ),
    )
    monkeypatch.setattr(
        ocr,
        "ocr_pdf",
        lambda _body: (_ for _ in ()).throw(ocr.OcrUnavailable("OCR kapalı.")),
    )

    with pytest.raises(documents.ScannedDocumentError, match="OCR kapalı"):
        source.fetch_detail("https://www.iskur.gov.tr/medya/12345/scanned.pdf")
