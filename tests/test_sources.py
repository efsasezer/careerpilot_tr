from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import main
from backend.backfill_sbb import backfill_existing_sbb_jobs
from backend.database import Base
from backend.models import CandidateProfile, Job, SourceListing, SourceSyncHistory
from backend.sources import iskur, osym, sbb, yerel_yonetimler
from backend.sources.base import SourceFetchError


def test_sbb_parser_finds_distinct_official_detail_links(monkeypatch):
    monkeypatch.setattr(
        sbb,
        "fetch_html",
        lambda _name, _url, **_kwargs: (
            "https://kamuilan.sbb.gov.tr/",
            """
            <a href="ilanDetay.aspx?kod=notice-1">Bilgisayar Mühendisi alımı</a>
            <a href="ilanDetay.aspx?kod=notice-1">Bilgisayar Mühendisi alımı</a>
            <a href="https://example.test/other">Diğer</a>
            """,
        ),
    )

    listings = sbb.SBBSource().fetch_listings()

    assert len(listings) == 1
    assert len(listings[0]["external_id"]) == 64
    assert listings[0]["title"] == "Bilgisayar Mühendisi alımı"
    assert listings[0]["application_end_date"] is None


def test_sbb_parser_extracts_structured_fields_and_deduplicates_list_items(monkeypatch):
    monkeypatch.setattr(
        sbb,
        "fetch_html",
        lambda _name, _url, **_kwargs: (
            "https://kamuilan.sbb.gov.tr/",
            """
            <a href="ilanDetay.aspx?kod=notice-1">
              <span class="black">T.C. Örnek Üniversitesi</span>
              <span class="patrol">2 Sözleşmeli Bilgisayar Mühendisi Alımı</span>
              <span class="h5date">(10 Kasım - 24 Kasım)</span>
            </a>
            <a href="ilanDetay.aspx?kod=duplicate-1">
              <span class="black">T.C. Örnek Üniversitesi</span>
              <span class="patrol">2 Sözleşmeli Bilgisayar Mühendisi Alımı</span>
              <span class="h5date">(10 Kasım - 24 Kasım)</span>
            </a>
            """,
        ),
    )

    listings = sbb.SBBSource().fetch_listings()

    assert len(listings) == 1
    listing = listings[0]
    assert listing["title"] == "2 Sözleşmeli Bilgisayar Mühendisi Alımı"
    assert listing["institution"] == "T.C. Örnek Üniversitesi"
    assert listing["position_title"] == listing["title"]
    assert listing["quota"] == "2"
    assert listing["employment_type"] == "Sözleşmeli"
    assert listing["recruitment_method"] == "Kaynakta belirtilmedi"
    assert listing["city"] is None
    assert listing["announcement_date"] is None
    assert listing["application_start_date"].month == 11
    assert listing["application_start_date"].day == 10
    assert listing["application_end_date"].month == 11
    assert listing["application_end_date"].day == 24
    assert "ilanDetay.aspx?kod=" in listing["detail_url"]


def test_sbb_detail_soft_404_is_reported_as_failure(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        content = "<html><body><h1>404</h1><p>Aradığınız sayfa bulunamadı</p></body></html>".encode("utf-8")
        text = content.decode("utf-8")
        encoding = apparent_encoding = "utf-8"

    source = sbb.SBBSource()
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs["headers"])
        return FakeResponse()

    monkeypatch.setattr(source._session, "get", fake_get)

    try:
        source.fetch_detail("https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=missing")
    except RuntimeError as error:
        assert "açılamadı" in str(error)
    else:
        raise AssertionError("A soft-404 must not be treated as an accessible detail.")
    # Detay, liste sayfası referansıyla aynı oturumdan istenir.
    assert seen["Referer"] == "https://kamuilan.sbb.gov.tr/"


def test_sbb_detail_pdf_is_parsed_as_official_document(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        content = b"%PDF-1.5 fake"

    source = sbb.SBBSource()
    monkeypatch.setattr(source._session, "get", lambda url, **kwargs: FakeResponse())
    monkeypatch.setattr(
        "backend.documents.parse_document",
        lambda url, body, content_type: {
            "text": "Resmî ilan metni " * 10, "positions": [], "shared_requirements": "", "links": [], "partially_read": False,
        },
    )

    detail = source.fetch_detail("https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=abc")

    assert detail["source_text"].startswith("Resmî ilan metni")
    assert detail["document"]["url"] == "https://kamuilan.sbb.gov.tr/"
    assert len(detail["document"]["body_hash"]) == 64


def test_sbb_quota_parser_keeps_compound_counts_and_project_based_quota():
    compound = sbb.parse_sbb_listing_label(
        "6 UZMAN, 1 DESTEK PERSONELİ ALACAK"
    )
    project_based = sbb.parse_sbb_listing_label(
        "SAVUNMA SANAYİİ BAŞKANLIĞI 26 PROJE BAZLI SÖZLEŞMELİ "
        "PERSONEL ALACAK 20 Kasım - 21 Aralık"
    )
    multi_suffix = sbb.parse_sbb_listing_label(
        "MİLLİ SARAYLAR İDARESİ BAŞKANLIĞI 38 SÖZLEŞMELİ "
        "PERSONEL ALACAK 7 Kasım - 17 Kasım"
    )

    assert compound["quota"] == "6 UZMAN, 1 DESTEK PERSONELİ"
    assert project_based["quota"] == "26"
    assert multi_suffix["institution"] == "MİLLİ SARAYLAR İDARESİ BAŞKANLIĞI"
    assert multi_suffix["title"] == "38 SÖZLEŞMELİ PERSONEL ALACAK"
    assert multi_suffix["quota"] == "38"


def test_sbb_backfill_updates_only_existing_rows_and_keeps_unmatched_snapshot():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    live_listing = {
        "listing_text": (
            "T.C. Örnek Üniversitesi 2 Sözleşmeli Bilgisayar Mühendisi Alımı "
            "(10 Kasım - 24 Kasım)"
        ),
        "title": "2 Sözleşmeli Bilgisayar Mühendisi Alımı",
        "institution": "T.C. Örnek Üniversitesi",
        "detail_url": "https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=live-1",
        "description_html": "T.C. Örnek Üniversitesi 2 Sözleşmeli Bilgisayar Mühendisi Alımı",
        "application_start_date": date(2026, 11, 10),
        "application_end_date": date(2026, 11, 24),
        "announcement_date": None,
        "city": None,
        "quota": "2",
        "employment_type": "Sözleşmeli",
        "recruitment_method": "Kaynakta belirtilmedi",
        "education_requirement": "",
        "qualification_codes": "",
        "kpss_score_type": "",
        "kpss_min_score": None,
    }

    with Session(engine) as db:
        db.add_all([
            Job(
                sector="public",
                title=live_listing["listing_text"],
                organization="SBB",
                source_url="https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=old-1",
                source_name="SBB Kamu İlanları",
                description="stale source automation title",
                application_deadline=date(2026, 11, 13),
                recruitment_method="Kaynak otomasyonu",
            ),
            Job(
                sector="public",
                title=(
                    "T.C. Örnek Bakanlığı 1 Uzman Personel Alımı "
                    "(1 Kasım - 9 Kasım)"
                ),
                organization="SBB",
                source_url="https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=old-snapshot",
                source_name="SBB Kamu İlanları",
                description="stored official title",
            ),
        ])
        db.commit()
        dry_run = backfill_existing_sbb_jobs(
            db, [live_listing], current_date=date(2026, 11, 14)
        )
        assert dry_run["existing"] == 2
        assert dry_run["matched_live"] == 1
        assert dry_run["matched_snapshot"] == 1
        assert dry_run["updated"] == 2
        assert list(db.scalars(select(Job).order_by(Job.id)).all())[0].organization == "SBB"

        applied = backfill_existing_sbb_jobs(
            db, [live_listing], apply=True, current_date=date(2026, 11, 14)
        )
        repeated = backfill_existing_sbb_jobs(
            db, [live_listing], current_date=date(2026, 11, 14)
        )
        refreshed_url = {
            **live_listing,
            "detail_url": "https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=live-rotated",
        }
        rotated = backfill_existing_sbb_jobs(
            db, [refreshed_url], current_date=date(2026, 11, 14)
        )
        jobs = list(db.scalars(select(Job).order_by(Job.id)).all())

    assert applied["updated"] == 2
    assert repeated["matched_live"] == 1
    assert repeated["matched_snapshot"] == 1
    assert repeated["updated"] == 0
    assert rotated["matched_live"] == 1
    assert rotated["updated"] == 0
    assert len(jobs) == 2
    assert jobs[0].title == live_listing["title"]
    assert jobs[0].organization == live_listing["institution"]
    assert jobs[0].city == ""
    assert jobs[0].application_start == date(2026, 11, 10)
    assert jobs[0].application_deadline == date(2026, 11, 24)
    assert jobs[0].announcement_date is None
    assert jobs[0].recruitment_method == "Kaynakta belirtilmedi"
    assert jobs[0].source_url == "https://kamuilan.sbb.gov.tr/"
    assert jobs[1].source_url == "https://kamuilan.sbb.gov.tr/"
    assert jobs[1].application_deadline == date(2026, 11, 9)


def test_sbb_match_api_keeps_official_fields_separate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(CandidateProfile(id=1))
        db.add(Job(
            sector="public",
            title="2 Sözleşmeli Bilgisayar Mühendisi Alımı",
            organization="T.C. Örnek Üniversitesi",
            city="",
            source_url="https://kamuilan.sbb.gov.tr/",
            source_name="SBB Kamu İlanları",
            description="Yalnızca resmî listede görüntülenen ilan bilgileri.",
            application_start=date(2099, 11, 10),
            application_deadline=date(2099, 11, 24),
            announcement_date=None,
            quota="2",
            employment_type="Sözleşmeli",
            recruitment_method="Kaynakta belirtilmedi",
        ))
        db.commit()
        response = main.public_matches(db)

    assert response["counts"]["total"] == 1
    job_view = response["jobs"][0]
    assert job_view["position"] == "2 Sözleşmeli Bilgisayar Mühendisi Alımı"
    assert job_view["organization"] == "T.C. Örnek Üniversitesi"
    assert job_view["city"] is None
    assert job_view["application_start"] == "2099-11-10"
    assert job_view["application_deadline"] == "2099-11-24"
    assert job_view["announcement_date"] is None
    assert job_view["employment_type"] == "Sözleşmeli"
    assert job_view["recruitment_method"] == "Kaynakta belirtilmedi"
    assert job_view["source_name"] == "SBB Kamu İlanları"


def test_yerel_yonetimler_traverses_all_pager_pages(monkeypatch):
    pages = {
        "https://yerelyonetimler.csb.gov.tr/duyurular": (
            "https://yerelyonetimler.csb.gov.tr/duyurular",
            """
            <a href="/ankara-belediyesi-memur-alimi-duyuru-100">05 Kasım 2026 Perşembe ANKARA İLİ ÖRNEK BELEDİYE BAŞKANLIĞINA İLK DEFA ATANMAK ÜZERE MEMUR ALIM İLANI...</a>
            <a href="/personel-gorusleri-duyuru-101">Personel Görüşleri</a>
            <a href="/iptal-duyuru-102">04 Kasım 2026 Çarşamba MUŞ İLİ ELMAKAYA BELEDİYESİNİN MEMUR ALIMI İPTAL İLANI</a>
            <a href="/duyurular/1">1</a><a href="/duyurular/2">2</a>
            """,
        ),
        "https://yerelyonetimler.csb.gov.tr/duyurular/2": (
            "https://yerelyonetimler.csb.gov.tr/duyurular/2",
            """
            <a href="/izmir-belediyesi-memur-alimi-duyuru-200">İZMİR BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞINA İLK DEFA ATANMAK ÜZERE ZABITA MEMURU ALIMI İLANI</a>
            <a href="/duyurular/1">1</a><a href="/duyurular/2">2</a>
            """,
        ),
    }
    monkeypatch.setattr(yerel_yonetimler, "fetch_html", lambda _name, url, **_kwargs: pages[url])

    source = yerel_yonetimler.YerelYonetimlerSource()
    listings = source.fetch_listings()

    assert source.pages_checked == 2
    # Rehber/görüş sayfaları ilan sayılmaz; iptal duyurusu ayrı işaretlenir.
    assert [item["external_id"] for item in listings] == ["100", "102", "200"]
    first, cancelled, last = listings
    assert first["institution"] == "Örnek Belediye Başkanlığı"
    assert first["city"] == "Ankara"
    assert first["announcement_date"] == date(2026, 11, 5)
    assert first["title"].startswith("ANKARA İLİ")
    assert cancelled["is_cancellation"] is True
    assert last["institution"] == "İzmir Büyükşehir Belediye Başkanlığı"


def test_yerel_yonetimler_checks_all_linked_documents_for_application_dates(monkeypatch):
    from backend import documents

    detail_url = "https://yerelyonetimler.csb.gov.tr/ornek-duyuru-100"
    monkeypatch.setattr(
        yerel_yonetimler,
        "fetch_html",
        lambda _name, _url: (
            detail_url,
            """
            <div class="haber-detay-wrapper">
              <p>Personel alım ilanı ve kurum bilgileri.</p>
              <a href="/files/kadro.pdf?download=1">Kadro listesi</a>
              <a href="/files/basvuru-takvimi.pdf">Başvuru takvimi</a>
            </div>
            """,
        ),
    )
    monkeypatch.setattr(documents, "_validate_official_url", lambda url: url)
    fetched = []

    def fake_fetch_url(url):
        fetched.append(url)
        return {
            "body": b"%PDF-1.4 example",
            "content_type": "application/pdf",
        }

    monkeypatch.setattr(documents, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(
        documents,
        "parse_document",
        lambda url, _body, _content_type: {
            "text": (
                "Başvurular 09/12/2026 - 11/12/2026 tarihleri arasında yapılacaktır."
                if "basvuru-takvimi" in url else "Kadro şartları ve pozisyon bilgileri. " * 5
            ),
            "shared_requirements": "",
            "positions": [],
            "links": [],
            "partially_read": False,
        },
    )

    detail = yerel_yonetimler.YerelYonetimlerSource().fetch_detail(detail_url)

    assert fetched == [
        "https://yerelyonetimler.csb.gov.tr/files/kadro.pdf?download=1",
        "https://yerelyonetimler.csb.gov.tr/files/basvuru-takvimi.pdf",
    ]
    assert "Başvurular 09/12/2026 - 11/12/2026" in detail["source_text"]
    assert detail["document"]["url"] == fetched[0]


def test_osym_checks_announcements_and_relevant_exam_lists(monkeypatch):
    source = osym.OsymSource()
    pages = {
        "https://www.osym.gov.tr/": '<a href="/2026-kpss-sinav-sonuclari">KPSS sınav sonuçları</a>',
        "https://www.osym.gov.tr/Duyurular/Index": (
            '<a href="/2026-kpss-2026-2-tercih-islemleri">'
            '2026-KPSS 2026/2 Tercih İşlemleri</a>'
        ),
        "https://www.osym.gov.tr/SinavGrubu/Index/3": (
            '<a href="/2026-kpss-2026-2-tercih-islemleri">'
            '2026-KPSS 2026/2 Tercih İşlemleri</a>'
        ),
        "https://www.osym.gov.tr/SinavGrubu/Index/4": (
            '<a href="/2026-ekpss-kura-tercih-islemleri">'
            '2026-EKPSS/Kura Tercih İşlemleri</a>'
        ),
    }
    checked = []

    def fake_get(url):
        checked.append(url)
        return url, pages[url]

    monkeypatch.setattr(source, "_get", fake_get)

    listings = source.fetch_listings()

    assert checked == list(pages)
    assert source.pages_checked == 4
    assert {item["title"] for item in listings} == {
        "2026-KPSS 2026/2 Tercih İşlemleri",
        "2026-EKPSS/Kura Tercih İşlemleri",
    }


def test_iskur_access_rejection_is_not_reported_as_empty_success(monkeypatch):
    def rejected(name, url):
        raise SourceFetchError(name, url, "Kaynak erişim kontrolü isteği reddetti.", 200)

    monkeypatch.setattr(iskur, "fetch_html", rejected)

    try:
        iskur.IskurSource().fetch_listings()
    except SourceFetchError as error:
        assert error.status_code == 200
        assert "reddetti" in str(error)
    else:
        raise AssertionError("Access-rejected source must not look like a successful empty scan.")


def test_positions_come_from_document_rows_without_invented_fields():
    from backend.matching import decompose_job_positions
    from backend.models import DocumentPosition, JobDocument

    job = Job(
        id=5,
        title="Sözleşmeli mühendis ve tekniker ilanı",
        organization="Örnek Kurum",
        description="Tüm pozisyonlar için ortak metin.",
        kpss_score_type="P3/P93",
    )
    document = JobDocument(id=9, job_id=5, document_url="https://x.gov.tr/a.pdf", shared_requirements="Türk vatandaşı olmak.")
    rows = [
        DocumentPosition(document_id=9, row_index=1, position_title="Mühendis", education_requirement="Makine Mühendisliği", quota="2", kpss_score_type="P3", kpss_min_score=70, city="Ankara", requirements_text="Makine Mühendisliği"),
        DocumentPosition(document_id=9, row_index=2, position_title="Tekniker", education_requirement="İnşaat Teknolojisi", quota="1", kpss_score_type="P93", kpss_min_score=None, city="", requirements_text="İnşaat Teknolojisi"),
    ]

    positions = decompose_job_positions(job, [document], {9: rows})
    without_rows = decompose_job_positions(job, [], {})

    assert [position["position"] for position in positions] == ["Mühendis", "Tekniker"]
    assert positions[0]["kpss_score_type"] == "P3" and positions[0]["kpss_min_score"] == 70
    assert positions[1]["kpss_score_type"] == "P93" and positions[1]["kpss_min_score"] is None
    assert positions[1]["city"] is None
    # Diğer satırların bölümleri karışmasın diye satır açıklamasına ilanın tam metni eklenmez.
    assert "ortak metin" not in positions[0]["description"]
    assert positions[0]["position_specific"] is True
    assert len(without_rows) == 1 and without_rows[0]["quota"] is None


def test_source_sync_fetches_details_once_and_persists_sync_state(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FixtureSource:
        source_name = "SBB Kamu İlanları"
        pages_checked = 1

        def __init__(self):
            self.detail_calls = 0

        def fetch_listings(self):
            return [{
                "detail_url": "https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=fixture-1",
                "external_id": "fixture-1",
                "title": "Bilgisayar Mühendisi Alımı",
                "institution": "Örnek Kurum",
                "content_hash": "same-list-hash",
            }]

        def fetch_detail(self, _url):
            self.detail_calls += 1
            text = (
                "Bilgisayar Mühendisi Alımı\nKurum: Örnek Kurum\n"
                "Başvuru Başlangıç Tarihi: 09.11.2026\n"
                "Son Başvuru Tarihi: 15.11.2026\n"
                "KPSS P3 taban puan 70. İlanın resmi açıklama ve başvuru şartları."
            )
            return {"source_text": text, "content_hash": "detail-hash"}

    source = FixtureSource()
    monkeypatch.setattr(main, "get_source_registry", lambda: {"sbb": source})
    monkeypatch.setenv("CAREERPILOT_SOURCE_REQUEST_DELAY_SECONDS", "0")

    with Session(engine) as db:
        first = main.sync_all_sources(db)
        second = main.sync_all_sources(db)
        jobs = list(db.scalars(select(Job)).all())
        links = list(db.scalars(select(SourceListing)).all())
        history = list(db.scalars(select(SourceSyncHistory).order_by(SourceSyncHistory.id)).all())

    assert first["success"] is True
    assert first["results"]["sbb"]["imported"] == 1
    assert second["results"]["sbb"]["unchanged"] == 1
    assert source.detail_calls == 1
    assert len(jobs) == 1
    assert jobs[0].application_start.isoformat() == "2026-11-09"
    assert jobs[0].application_deadline.isoformat() == "2026-11-15"
    assert len(links) == 1 and links[0].status == "complete"
    assert len(history) == 2 and all(row.status == "ok" for row in history)


def test_sbb_listing_sync_uses_stable_identity_and_official_index_url(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class RotatingLinkSource:
        source_name = "SBB Kamu İlanları"
        pages_checked = 1

        def __init__(self):
            self.fetch_count = 0
            self.detail_calls = 0

        def fetch_listings(self):
            self.fetch_count += 1
            return [{
                "source_key": "sbb",
                "source_name": self.source_name,
                "source_url": "https://kamuilan.sbb.gov.tr/",
                "user_url": "https://kamuilan.sbb.gov.tr/",
                "detail_url": f"https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=rotating-{self.fetch_count}",
                "external_id": "stable-listing-identity",
                "title": "1 Sözleşmeli Mühendis Alımı",
                "institution": "Örnek Üniversitesi",
                "quota": "1",
                "employment_type": "Sözleşmeli",
                "application_start_date": date(2026, 11, 10),
                "application_end_date": date(2026, 11, 24),
                "content_hash": "stable-listing-content",
            }]

        def fetch_detail(self, _url):
            self.detail_calls += 1
            return {
                "source_text": "Makine Mühendisliği bölümünden mezun olmak. KPSS P3 puan türünden en az 70 puan almış olmak. " * 2,
                "content_hash": "detail",
                "document": {
                    "url": "https://kamuilan.sbb.gov.tr/", "title": "Resmî ilan metni", "content_type": "application/pdf",
                    "body_hash": "a" * 64,
                    "parsed": {"text": "Belge metni", "shared_requirements": "", "partially_read": False, "positions": [
                        {"row_index": 1, "position_title": "Mühendis", "education_requirement": "Makine Mühendisliği", "quota": "1", "kpss_score_type": "P3", "kpss_min_score": 70.0},
                    ]},
                },
            }

    source = RotatingLinkSource()
    monkeypatch.setattr(main, "get_source_registry", lambda: {"sbb": source})

    with Session(engine) as db:
        first = main.sync_all_sources(db)
        second = main.sync_all_sources(db)
        jobs = list(db.scalars(select(Job)).all())
        links = list(db.scalars(select(SourceListing)).all())
        matches = main.public_matches(db)

    assert first["results"]["sbb"]["status"] == "ok"
    assert first["results"]["sbb"]["imported"] == 1
    assert second["results"]["sbb"]["unchanged"] == 1
    assert source.detail_calls == 1  # liste değişmedikçe detay yeniden indirilmez
    assert len(jobs) == 1
    assert jobs[0].source_url == "https://kamuilan.sbb.gov.tr/"
    assert jobs[0].kpss_score_type == "P3" and jobs[0].kpss_min_score == 70
    assert len(links) == 1 and links[0].status == "complete"
    assert links[0].official_url.endswith("rotating-2")
    assert [item["position"] for item in matches["jobs"]] == ["Mühendis"]


def test_detail_failure_keeps_listing_and_reports_partial(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class BrokenDetailSource:
        source_name = "İŞKUR Kamu Memur Alım İlanları"
        pages_checked = 1

        def fetch_listings(self):
            return [{
                "detail_url": "https://www.iskur.gov.tr/medya/x/ilan.pdf",
                "external_id": "ilan",
                "title": "Örnek Belediyesi Memur Alım İlanı",
                "institution": "Örnek Belediyesi",
                "application_end_date": date(2099, 1, 5),
                "content_hash": "h",
            }]

        def fetch_detail(self, _url):
            raise RuntimeError("PDF okunamadı")

    monkeypatch.setattr(main, "get_source_registry", lambda: {"iskur": BrokenDetailSource()})
    with Session(engine) as db:
        result = main.sync_all_sources(db)
        job = db.scalar(select(Job))
        listing = db.scalar(select(SourceListing))

    assert result["success"] is False
    assert result["results"]["iskur"]["status"] == "partial"
    assert result["results"]["iskur"]["detail_failed"] == 1
    assert job.title == "Örnek Belediyesi Memur Alım İlanı"
    assert job.application_deadline == date(2099, 1, 5)
    assert listing.status == "detail_failed"


def test_source_sync_failure_is_persisted_and_never_reported_as_success(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class BlockedSource:
        source_name = "SBB Kamu İlanları"
        pages_checked = 0

        def fetch_listings(self):
            raise SourceFetchError(self.source_name, "https://example.test", "HTTP 403", 403)

    monkeypatch.setattr(
        main,
        "get_source_registry",
        lambda: {"sbb": BlockedSource()},
    )

    with Session(engine) as db:
        result = main.sync_all_sources(db)
        history = db.scalar(select(SourceSyncHistory))

    assert result["success"] is False
    assert result["results"]["sbb"]["status"] == "error"
    assert "403" in history.error
