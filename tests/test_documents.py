from __future__ import annotations

import os
from io import BytesIO
from hashlib import sha256
from urllib.parse import urlsplit

import pytest
from docx import Document
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import documents
from backend.document_sync import _sync_document, sync_jobs_documents
from backend.eligibility import build_candidate_profile, classify_public_job
from backend.kariyerkapisi import scrape_public_listing_details
from backend.models import (
    CandidateProfile,
    DocumentPosition,
    Job,
    JobDocument,
    JobDocumentScan,
)


TURKSEKER_DETAIL_URL = (
    "https://kariyerkapisi.gov.tr/IlanDetay?"
    "i=06fcbe8a-50bf-4b51-9ba1-9cc4ad6501f3"
)
TURKSEKER_PDF_URL = (
    "https://kariyerkapisi.gov.tr/Ups/Evraklar/Tablo1-turkseker-051126.pdf"
)
RUN_LIVE_DOCUMENT_TESTS = os.getenv("CAREERPILOT_LIVE_DOCUMENT_TESTS") == "1"


def test_discovers_official_pdf_attachment_by_link_and_text(monkeypatch):
    def validate(url):
        if not (urlsplit(url).hostname or "").endswith(".gov.tr"):
            raise documents.DocumentFetchError("Not an official domain")
        return url

    monkeypatch.setattr(documents, "_validate_official_url", validate)
    links = documents.discover_document_links(
        "https://kariyerkapisi.gov.tr/IlanDetay?i=example",
        """
        <a href="/Ups/Evraklar/Tablo1.pdf">Tablo 1 Başvuru Şartları</a>
        <a href="/IlanDetay?i=other">Başka ilan</a>
        <a href="https://example.com/guide.pdf">Harici belge</a>
        """,
    )
    assert links == [{
        "url": "https://kariyerkapisi.gov.tr/Ups/Evraklar/Tablo1.pdf",
        "title": "Tablo 1 Başvuru Şartları",
    }]


@pytest.mark.parametrize("file_type", ["html", "docx"])
def test_html_and_docx_position_tables_keep_fields_together(file_type):
    headers = [
        "Öğrenim şartı",
        "Atama yapılacak pozisyon sayısı",
        "KPSS puan türü",
        "KPSS taban puan",
        "Atanacağı il/ilçe",
    ]
    values = [
        "Bilgisayar Mühendisliği ve eşdeğer programlar",
        "2",
        "P3",
        "70",
        "Ankara",
    ]
    if file_type == "html":
        markup = (
            "<table><tr>"
            + "".join(f"<th>{cell}</th>" for cell in headers)
            + "</tr><tr>"
            + "".join(f"<td>{cell}</td>" for cell in values)
            + "</tr></table>"
        )
        parsed = documents.parse_document(
            "https://kariyerkapisi.gov.tr/ek.html",
            markup.encode(),
            "text/html; charset=utf-8",
        )
    else:
        word = Document()
        table = word.add_table(rows=1, cols=len(headers))
        for cell, value in zip(table.rows[0].cells, headers):
            cell.text = value
        row = table.add_row()
        for cell, value in zip(row.cells, values):
            cell.text = value
        stream = BytesIO()
        word.save(stream)
        parsed = documents.parse_document(
            "https://kariyerkapisi.gov.tr/ek.docx",
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    assert len(parsed["positions"]) == 1
    position = parsed["positions"][0]
    assert position["education_requirement"] == values[0]
    assert position["quota"] == "2"
    assert position["kpss_score_type"] == "P3"
    assert position["kpss_min_score"] == 70
    assert position["city"] == "Ankara"


@pytest.mark.skipif(
    not RUN_LIVE_DOCUMENT_TESTS,
    reason="Set CAREERPILOT_LIVE_DOCUMENT_TESTS=1 to fetch the official regression documents.",
)
def test_live_turkseker_attachment_and_pdf_table_regression():
    outcome = scrape_public_listing_details([{"url": TURKSEKER_DETAIL_URL}])[TURKSEKER_DETAIL_URL]
    assert outcome["error"] is None
    attachment_urls = {item["url"] for item in outcome["details"]["attachments"]}
    assert TURKSEKER_PDF_URL in attachment_urls

    fetched = documents.fetch_url(TURKSEKER_PDF_URL)
    assert not fetched["not_modified"]
    assert fetched["body"].startswith(b"%PDF-")
    parsed = documents.parse_document(
        fetched["url"], fetched["body"], fetched["content_type"]
    )
    rows = parsed["positions"]
    computer = next(
        row for row in rows
        if "Bilgisayar Mühendisliği" in row["education_requirement"]
    )
    electrical = next(
        row for row in rows
        if row["education_requirement"].startswith("Elektrik ve Elektronik")
    )

    assert len(rows) == 10
    normalized_education = " ".join(computer["education_requirement"].split())
    assert "Bilgisayar Bilimleri Mühendisliği" in normalized_education
    assert "Bilişim Sistemleri Mühendisliği" in normalized_education
    assert computer["quota"] == "2"
    assert computer["kpss_score_type"] == "P3"
    assert computer["kpss_min_score"] == 70
    assert computer["city"] == "Ankara (2)"
    assert computer["written_exam_invite_count"] == 5
    assert electrical["quota"] == "6"
    assert "Ankara (2)" in electrical["city"]
    assert electrical["quota"] != computer["quota"]

    candidate = build_candidate_profile({
        "degree": "Lisans",
        "department": "Bilgisayar Mühendisliği",
        "kpss_score_type": "P3",
        "kpss_p3": 87.60,
        "preferred_locations": "Türkiye geneli",
    })
    result = classify_public_job({
        "title": "Türkşeker sözleşmeli mühendis alımı",
        "position": computer["position_title"],
        "description": computer["education_requirement"],
        "education_requirement": computer["education_requirement"],
        "qualification_codes": computer["qualification_codes"],
        "kpss_score_type": computer["kpss_score_type"],
        "kpss_min_score": computer["kpss_min_score"],
    }, candidate)
    assert result["education"]["status"] == "met"
    assert result["kpss"]["status"] == "met"
    assert result["category"] != "UYGUN DEĞİL"


def test_unchanged_document_uses_conditional_response_without_reparsing(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    from backend.database import Base

    Base.metadata.create_all(engine)
    body = b"%PDF-unchanged"
    with Session(engine) as db:
        job = Job(sector="public", title="Kamu ilanı", source_name="Kariyer Kapısı")
        db.add(job)
        db.flush()
        document = JobDocument(
            job_id=job.id,
            document_url=TURKSEKER_PDF_URL,
            content_hash=sha256(body).hexdigest(),
            parsed_content_hash=sha256(body).hexdigest(),
            etag='"official-etag"',
            status="read",
            extracted_text="Daha önce ayrıştırılmış içerik",
        )
        db.add(document)
        db.flush()
        monkeypatch.setattr(
            "backend.document_sync.fetch_url",
            lambda url, **kwargs: {
                "not_modified": True,
                "url": url,
                "etag": kwargs["etag"],
                "last_modified": kwargs.get("last_modified"),
                "content_type": "application/pdf",
                "body": b"",
            },
        )
        report = {"read": 0, "unchanged": 0, "positions": 0, "errors": 0, "details": []}

        _sync_document(db, job, {"url": TURKSEKER_PDF_URL}, set(), report)

        assert report["unchanged"] == 1
        assert report["read"] == 0
        assert document.extracted_text == "Daha önce ayrıştırılmış içerik"
        assert db.scalar(select(DocumentPosition).where(
            DocumentPosition.document_id == document.id
        )) is None


def test_document_sync_skips_non_vacancy_local_government_pages(monkeypatch):
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        reference_page = Job(
            sector="public",
            title="Personel Görüşleri",
            source_name="Yerel Yönetimler Genel Müdürlüğü",
            source_url="https://yerelyonetimler.csb.gov.tr/personel-gorusleri-i-98889",
        )
        vacancy_page = Job(
            sector="public",
            title="Belediye memur alımı",
            source_name="Yerel Yönetimler Genel Müdürlüğü",
            source_url="https://yerelyonetimler.csb.gov.tr/example-duyuru-123",
        )
        db.add_all([reference_page, vacancy_page])
        db.flush()
        scanned_job_ids = []

        def fake_sync_job_documents(_db, job, **_kwargs):
            scanned_job_ids.append(job.id)
            return {
                "status": "complete",
                "found": 0,
                "read": 0,
                "unchanged": 0,
                "positions": 0,
                "errors": 0,
                "details": [],
            }

        monkeypatch.setattr(
            "backend.document_sync.sync_job_documents",
            fake_sync_job_documents,
        )

        report = sync_jobs_documents(db, [reference_page, vacancy_page])

        assert report["jobs_scanned"] == 1
        assert report["jobs_skipped"] == 1
        assert scanned_job_ids == [vacancy_page.id]


def test_changed_document_is_reparsed_and_replaces_derived_rows(monkeypatch):
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    new_body = b"%PDF-updated"
    with Session(engine) as db:
        job = Job(sector="public", title="Kamu ilanı")
        db.add(job)
        db.flush()
        document = JobDocument(
            job_id=job.id,
            document_url=TURKSEKER_PDF_URL,
            content_hash="previous-hash",
            parsed_content_hash="previous-hash",
            etag='"previous"',
            status="read",
        )
        db.add(document)
        db.flush()
        old_position = DocumentPosition(
            document_id=document.id,
            row_index=1,
            education_requirement="Eski satır",
        )
        db.add(old_position)
        db.flush()
        monkeypatch.setattr(
            "backend.document_sync.fetch_url",
            lambda *_args, **_kwargs: {
                "not_modified": False,
                "url": TURKSEKER_PDF_URL,
                "etag": '"updated"',
                "last_modified": "Sat, 14 Nov 2026 10:00:00 GMT",
                "content_type": "application/pdf",
                "body": new_body,
            },
        )
        monkeypatch.setattr(
            "backend.document_sync.parse_document",
            lambda *_args: {
                "text": "Updated official attachment content",
                "shared_requirements": "",
                "positions": [{
                    "row_index": 2,
                    "position_title": "Bilgisayar Mühendisliği",
                    "education_requirement": "Bilgisayar Mühendisliği",
                    "quota": "2",
                    "kpss_score_type": "P3",
                    "kpss_min_score": 70,
                    "city": "Ankara",
                    "qualification_codes": "",
                    "written_exam_invite_text": "",
                    "written_exam_invite_count": None,
                    "requirements_text": "Bilgisayar Mühendisliği",
                    "raw_cells": {},
                }],
                "links": [],
                "partially_read": False,
            },
        )
        report = {"read": 0, "unchanged": 0, "positions": 0, "errors": 0, "details": []}

        _sync_document(db, job, {"url": TURKSEKER_PDF_URL}, set(), report)

        rows = list(db.scalars(
            select(DocumentPosition).where(DocumentPosition.document_id == document.id)
        ))
        assert report["read"] == 1
        assert document.content_hash == sha256(new_body).hexdigest()
        assert document.parsed_content_hash == document.content_hash
        assert document.etag == '"updated"'
        assert len(rows) == 1
        assert rows[0].row_index == 2
        assert rows[0].education_requirement == "Bilgisayar Mühendisliği"


def test_temporary_document_failure_keeps_previous_extraction(monkeypatch):
    from backend.database import Base
    from backend.documents import DocumentFetchError

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = Job(sector="public", title="Kamu ilanı")
        db.add(job)
        db.flush()
        document = JobDocument(
            job_id=job.id,
            document_url=TURKSEKER_PDF_URL,
            status="read",
            content_hash="old-hash",
            parsed_content_hash="old-hash",
            extracted_text="Önceki resmî belge metni",
        )
        db.add(document)
        db.flush()
        position = DocumentPosition(
            document_id=document.id,
            row_index=1,
            education_requirement="Bilgisayar Mühendisliği",
            quota="2",
        )
        db.add(position)
        db.flush()
        monkeypatch.setattr(
            "backend.document_sync.fetch_url",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                DocumentFetchError("Geçici kaynak erişim hatası")
            ),
        )
        report = {"read": 0, "unchanged": 0, "positions": 0, "errors": 0, "details": []}

        _sync_document(db, job, {"url": TURKSEKER_PDF_URL}, set(), report)

        assert document.status == "unavailable"
        assert document.content_hash == "old-hash"
        assert document.parsed_content_hash == "old-hash"
        assert document.extracted_text == "Önceki resmî belge metni"
        assert db.scalar(select(DocumentPosition).where(
            DocumentPosition.document_id == document.id
        )).quota == "2"


def test_document_rows_reach_matches_api_without_sharing_adjacent_requirements():
    from backend import main
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CandidateProfile(
            id=1,
            degree="Lisans",
            department="Bilgisayar Mühendisliği",
            kpss_score_type="P3",
            kpss_p3=87.60,
            preferred_locations="Türkiye geneli",
        ))
        job = Job(
            sector="public",
            title="Türkiye Şeker Fabrikaları sözleşmeli alımı",
            organization="Türkiye Şeker Fabrikaları A.Ş.",
            source_name="Kariyer Kapısı",
            source_url=TURKSEKER_DETAIL_URL,
            description="1.1- 399 sayılı KHK genel şartlarını taşımak.",
            is_employment=True,
        )
        db.add(job)
        db.flush()
        document = JobDocument(
            job_id=job.id,
            document_url=TURKSEKER_PDF_URL,
            title="Tablo 1",
            status="read",
            content_hash="pdf-hash",
            parsed_content_hash="pdf-hash",
        )
        db.add(document)
        db.add(JobDocumentScan(job_id=job.id, status="complete", attachments_found=1))
        db.flush()
        db.add_all([
            DocumentPosition(
                document_id=document.id,
                row_index=4,
                position_title="Bilgisayar Mühendisliği",
                education_requirement=(
                    "Bilgisayar Mühendisliği, Bilgisayar Bilimleri Mühendisliği, "
                    "Bilgisayar Bilimi ve Mühendisliği, Bilişim Sistemleri Mühendisliği"
                ),
                quota="2",
                kpss_score_type="P3",
                kpss_min_score=70,
                city="Ankara (2)",
                written_exam_invite_text="Her pozisyon için 5 katına kadar.",
                written_exam_invite_count=5,
            ),
            DocumentPosition(
                document_id=document.id,
                row_index=12,
                position_title="Elektrik ve Elektronik Mühendisliği",
                education_requirement="Elektrik ve Elektronik Mühendisliği",
                quota="6",
                kpss_score_type="P3",
                kpss_min_score=70,
                city="Afyon (1), Kastamonu (1)",
            ),
        ])
        db.flush()

        response = main.public_matches(db)

    computer = next(
        row for row in response["jobs"]
        if row["position"] == "Bilgisayar Mühendisliği"
    )
    electrical = next(
        row for row in response["jobs"]
        if row["position"] == "Elektrik ve Elektronik Mühendisliği"
    )
    assert computer["quota"] == "2"
    assert computer["city"] == "Ankara (2)"
    assert computer["kpss_score_type"] == "P3"
    assert computer["kpss_min_score"] == 70
    assert computer["written_exam_invite_count"] == 5
    assert computer["match"]["education"]["status"] == "met"
    assert computer["match"]["kpss"]["status"] == "met"
    assert computer["match"]["category"] != "UYGUN DEĞİL"
    assert electrical["quota"] == "6"
    assert electrical["city"] == "Afyon (1), Kastamonu (1)"
    assert electrical["match"]["education"]["status"] == "not_met"
