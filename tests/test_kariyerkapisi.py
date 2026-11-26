from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

import backend.kariyerkapisi as kariyerkapisi
from backend.kariyerkapisi import parse_listing_content, parse_listing_detail
from backend.eligibility import build_candidate_profile as _build_candidate_profile, classify_public_job
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import main
from backend.database import Base
from backend.models import CandidateProfile, Job


def test_navigation_retries_transient_dns_errors(monkeypatch):
    delays = []
    monkeypatch.setattr(kariyerkapisi.time, "sleep", delays.append)

    class Page:
        calls = 0

        def goto(self, _url, **_kwargs):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")
            return "loaded"

    page = Page()

    assert kariyerkapisi._goto_with_retries(
        page,
        kariyerkapisi.URL,
        wait_until="domcontentloaded",
    ) == "loaded"
    assert page.calls == 3
    assert delays == [1.5, 3.0]


def test_active_listing_does_not_report_persistent_dns_failure_as_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(kariyerkapisi, "_playwright_event_loop_policy", nullcontext)
    monkeypatch.setattr(kariyerkapisi.time, "sleep", lambda _delay: None)

    class Page:
        def route(self, *_args):
            pass

        def on(self, *_args):
            pass

        def goto(self, *_args, **_kwargs):
            calls.append("goto")
            raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")

        def close(self):
            pass

    class Browser:
        def new_page(self, **_kwargs):
            return Page()

        def close(self):
            pass

    class Chromium:
        def launch(self, **_kwargs):
            return Browser()

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=Chromium())

    monkeypatch.setattr(kariyerkapisi, "sync_playwright", fake_playwright)

    with pytest.raises(RuntimeError, match="3 denemede yüklenemedi"):
        kariyerkapisi.scrape_public_active_listings()

    assert calls == ["goto", "goto", "goto"]


def test_detail_api_dns_failure_is_retried_and_not_reported_as_success(monkeypatch):
    detail_url = "https://kariyerkapisi.gov.tr/IlanDetay?i=unavailable"
    monkeypatch.setattr(kariyerkapisi, "_playwright_event_loop_policy", nullcontext)
    monkeypatch.setattr(kariyerkapisi.time, "sleep", lambda _delay: None)
    calls = []

    class Response:
        status = 200

    class Page:
        def __init__(self):
            self.handlers = {}

        def route(self, *_args):
            pass

        def on(self, event, callback):
            self.handlers[event] = callback

        def goto(self, *_args, **_kwargs):
            calls.append("goto")
            self.handlers["requestfailed"](SimpleNamespace(
                url="https://api.kariyerkapisi.gov.tr/api/ilan/GetIlan",
                failure="net::ERR_NAME_NOT_RESOLVED",
            ))
            return Response()

        def wait_for_load_state(self, *_args, **_kwargs):
            pass

        def locator(self, *_args):
            pytest.fail("A failed API response must not be parsed as a successful detail.")

    class Browser:
        def new_page(self, **_kwargs):
            return Page()

        def close(self):
            pass

    class Chromium:
        def launch(self, **_kwargs):
            return Browser()

    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=Chromium())

    monkeypatch.setattr(kariyerkapisi, "sync_playwright", fake_playwright)

    outcome = kariyerkapisi.scrape_public_listing_details([{"url": detail_url}])[detail_url]

    assert calls == ["goto", "goto", "goto"]
    assert outcome["details"]["source_text"] == ""
    assert "api.kariyerkapisi.gov.tr" in outcome["error"]
    assert "ERR_NAME_NOT_RESOLVED" in outcome["error"]


def build_candidate_profile():
    return _build_candidate_profile({
        "degree": "Lisans",
        "department": "Bilgisayar Mühendisliği",
        "kpss_p3": 87.60,
    })


def test_turkish_date_parser_accepts_detail_time_suffix():
    assert main.parse_turkish_date("11.11.2026 / 13:00")
    assert main.parse_turkish_date("11.11.2026 / 13:00").isoformat() == "2026-11-11"


def test_detail_snapshot_omits_changing_countdown_text():
    result = parse_listing_content(
        "Sistem Yöneticisi\nKalan Süre: 2 gün 03:12:10\nBaşvuru şartları",
    )
    assert "Sistem Yöneticisi" in result["source_text"]
    assert "Başvuru şartları" in result["source_text"]
    assert "Kalan Süre" not in result["source_text"]


def test_repeated_content_parsing_returns_independent_results():
    text = "Kontenjan: 2\nBaşvuru şartları"
    first = parse_listing_content(text)
    first["source_text"] = "değiştirildi"

    second = parse_listing_content(text)

    assert second["quota"] == "2"
    assert second["source_text"] == text


def test_detail_parser_reads_explicit_public_fields_from_html():
    html = """
    <html><body>
      <table>
        <tr><th>Kurum Adı</th><td>Burdur Mehmet Akif Ersoy Üniversitesi</td></tr>
        <tr><th>Pozisyon</th><td>Sistem Yöneticisi</td></tr>
        <tr><th>Kontenjan</th><td>1</td></tr>
        <tr><th>Başvuru Başlangıç Tarihi</th><td>28.10.2026</td></tr>
        <tr><th>Son Başvuru Tarihi</th><td>11.11.2026</td></tr>
      </table>
      <p>KPSS P3 puanının en az 70 olması gerekir.</p>
    </body></html>
    """

    result = parse_listing_detail(html, "https://kariyerkapisi.gov.tr/IlanDetay?i=123")

    assert result["institution"] == "Burdur Mehmet Akif Ersoy Üniversitesi"
    assert result["position"] == "Sistem Yöneticisi"
    assert result["quota"] == "1"
    assert result["start_date"] == "28.10.2026"
    assert result["end_date"] == "11.11.2026"
    assert result["kpss_score_type"] == "P3"
    assert result["kpss_min_score"] == 70.0


def test_detail_parser_does_not_invent_unlabeled_requirements():
    html = """
    <html><body>
      <p>İlan Yayım Tarihi: 28.10.2026</p>
      <p>Başvuru adayları değerlendirilir.</p>
      <p>Bilgisayar Mühendisliği mezunu adaylar tercih edilir.</p>
      <p>KPSS P3 puanının yüzde yetmişi alınacaktır.</p>
    </body></html>
    """

    result = parse_listing_detail(html, "https://kariyerkapisi.gov.tr/ilan/456")

    assert "education_requirement" not in result
    assert "departments" not in result
    assert "kpss_min_score" not in result
    assert "city" not in result
    assert result["kpss_score_type"] == "P3"


def test_department_list_does_not_become_a_generic_bachelors_requirement():
    result = parse_listing_detail(
        "<p>Fakültelerin dört yıllık bilgisayar mühendisliği ve yazılım mühendisliği "
        "bölümlerinden mezun olmak.</p>",
        "https://kariyerkapisi.gov.tr/IlanDetay?i=degree",
    )

    assert "bilgisayar mühendisliği" in result["departments"].casefold()
    assert "education_requirement" not in result


def test_sync_enriches_existing_job_without_changing_status_or_notes(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    url = "https://kariyerkapisi.gov.tr/IlanDetay?i=one"
    failed_url = "https://kariyerkapisi.gov.tr/IlanDetay?i=two"

    class Source:
        source_name = "Kariyer Kapısı"
        pages_checked = 1

        def fetch_listings(self):
            return [
                {"detail_url": url, "external_id": "one", "title": "Yeni başlık", "institution": "Kurum", "application_end_date": "09 Kasım 2026", "content_hash": "a"},
                {"detail_url": failed_url, "external_id": "two", "title": "İkinci ilan", "institution": "Başka Kurum", "content_hash": "b"},
            ]

        def fetch_detail(self, detail_url):
            if detail_url == failed_url:
                raise RuntimeError("HTTP 503")
            return {
                "title": "Yeni başlık", "position": "Uzman", "quota": "1",
                "start_date": "01.11.2026", "end_date": "09 Kasım 2026",
                "kpss_score_type": "P3", "education_requirement": "Lisans",
                "departments": "Bilgisayar Mühendisliği", "qualification_codes": "",
                "city": "Burdur", "source_text": "Resmî ilan metni. " * 8, "content_hash": "d",
            }

    monkeypatch.setattr(main, "get_source_registry", lambda: {"kariyer-kapisi": Source()})
    monkeypatch.setattr("backend.sync.sync_jobs_documents", lambda db, jobs: {"errors": 0})

    with Session(engine) as db:
        db.add(Job(
            sector="public", title="Eski başlık", organization="Kurum", source_url=url,
            description="Eski açıklama", status="Başvuruldu", notes="Kullanıcı notu", tracking="applied",
        ))
        db.commit()

        result = main.sync_all_sources(db)["results"]["kariyer-kapisi"]
        saved = db.scalar(select(Job).where(Job.source_url == url))

        assert result["imported"] == 1
        assert result["updated"] == 1
        assert result["detail_failed"] == 1
        assert result["status"] == "partial"
        assert saved.title == "Yeni başlık"
        assert saved.kpss_score_type == "P3"
        assert saved.education_requirement == "Bilgisayar Mühendisliği"
        assert saved.city == "Burdur"
        assert saved.application_start.isoformat() == "2026-11-01"
        assert saved.application_deadline.isoformat() == "2026-11-09"
        # Kullanıcının takip bilgileri senkronizasyonda korunur.
        assert saved.status == "Başvuruldu"
        assert saved.notes == "Kullanıcı notu"
        assert saved.tracking == "applied"
        assert "Resmî ilan metni" in saved.description

        second = main.sync_all_sources(db)["results"]["kariyer-kapisi"]
        assert second["imported"] == 0


def test_public_matches_returns_department_score_and_unknown_details():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(CandidateProfile(
            id=1,
            degree="Lisans",
            department="Bilgisayar Mühendisliği",
            kpss_p3=87.60,
        ))
        db.add(Job(
            sector="public",
            title="Bilişim Personeli",
            organization="Kurum",
            education_requirement="Lisans (ilan metninde dört yıllık fakülte mezuniyeti belirtilmiş)",
            kpss_score_type="P3",
            kpss_min_score=70,
            description=(
                "Fakültelerin dört yıllık bilgisayar mühendisliği bölümlerinden mezun olmak. "
                "KPSS P3 puanının en az 70 olması gerekir. En az 3 yıl deneyim sahibi olmak."
            ),
        ))
        db.commit()

        result = main.public_matches(db)

    job = result["jobs"][0]
    assert result["counts"]["total"] == 1
    assert job["match"]["education"]["computer_engineering"] == "KABUL EDİLİYOR"
    assert "dört yıllık bilgisayar mühendisliği bölümlerinden" in job["education_requirement"]
    assert job["match"]["kpss"]["status"] == "met"
    assert job["kpss_score_type"] == "P3"
    assert job["kpss_min_score"] == 70
    assert any("deneyim" in item for item in job["match"]["unknown_conditions"])
    assert job["match"]["category"] == "POTANSİYEL OLARAK UYGUN"


def test_p3_87_60_meets_p3_minimum_80():
    profile = build_candidate_profile()
    job = {"title": "Uzman", "education_requirement": "Lisans Bilgisayar Mühendisliği", "kpss_score_type": "P3", "kpss_min_score": 80, "description": ""}
    result = classify_public_job(job, profile)
    assert "87.60" in result["reason"]
    assert result["category"] == "UYGUN"


def test_empty_profile_does_not_invent_department_or_kpss_score():
    profile = _build_candidate_profile({})

    assert profile["department"] == ""
    assert profile["kpss_score_type"] == ""
    assert profile["kpss_score"] is None


def test_p3_score_equal_to_minimum_is_met():
    profile = build_candidate_profile()
    job = {
        "title": "Uzman",
        "education_requirement": "Bilgisayar Mühendisliği mezunu olmak",
        "kpss_score_type": "P3",
        "kpss_min_score": 87.6,
        "description": "",
    }

    result = classify_public_job(job, profile)

    assert result["kpss"]["status"] == "met"
    assert result["category"] == "UYGUN"


def test_explicit_non_p3_requirement_is_not_eligible():
    profile = build_candidate_profile()
    job = {
        "title": "Memur",
        "education_requirement": "Bilgisayar Mühendisliği mezunu olmak",
        "kpss_score_type": "P94",
        "kpss_min_score": 70,
        "description": "",
    }

    result = classify_public_job(job, profile)

    assert result["kpss"]["status"] == "not_met"
    assert result["category"] == "UYGUN DEĞİL"


def test_experience_after_graduation_is_not_read_as_any_bachelors():
    profile = build_candidate_profile()
    job = {
        "title": "Uzman",
        "education_requirement": "Lisans",
        "description": "Lisans mezuniyetinden sonra en az 3 yıl deneyim sahibi olmak.",
    }

    result = classify_public_job(job, profile)

    assert result["education"]["status"] == "unknown"
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"


def test_explicit_any_bachelors_requirement_is_met():
    profile = build_candidate_profile()
    job = {
        "title": "Uzman",
        "education_requirement": "Herhangi bir lisans programından mezun olmak",
        "description": "",
    }

    result = classify_public_job(job, profile)

    assert result["education"]["status"] == "met"
    assert result["education"]["computer_engineering"] == "KABUL EDİLİYOR"
    assert result["category"] == "UYGUN"


def test_it_notice_accepts_computer_engineering_and_score_but_keeps_unknown_experience():
    profile = build_candidate_profile()
    job = {
        "title": "Bilişim Personeli",
        "education_requirement": "Lisans (ilan metninde dört yıllık fakülte mezuniyeti belirtilmiş)",
        "kpss_score_type": "P3",
        "description": (
            "Fakültelerin dört yıllık bilgisayar mühendisliği bölümlerinden mezun olmak. "
            "KPSS P3 puanı olmayan adayın puanı 70 olarak değerlendirilecektir. "
            "Yabancı dil puanı olmayan adayın puanı 0 (sıfır) olarak değerlendirilecektir. "
            "En az 3 yıl iş deneyimine sahip olmak. "
            "Güncel programlama dillerinden en az ikisini bildiğini belgelemek. "
            "Güvenlik soruşturması ve arşiv araştırması yapılacaktır."
        ),
    }

    result = classify_public_job(job, profile)

    assert result["education"]["computer_engineering"] == "KABUL EDİLİYOR"
    assert result["kpss"]["status"] == "met"
    assert any("deneyim" in item for item in result["unknown_conditions"])
    assert any("programlama" in item for item in result["unknown_conditions"])
    assert not any("YDS" in item for item in result["unknown_conditions"])
    assert not any("Güvenlik" in item or "Arşiv" in item for item in result["unknown_conditions"])
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"


def test_preferred_certificate_is_not_a_missing_mandatory_condition():
    profile = build_candidate_profile()
    job = {
        "title": "Uzman",
        "education_requirement": "Bilgisayar Mühendisliği mezunu olmak",
        "description": "Tercihen CISSP sertifikasına sahip olmak.",
    }

    result = classify_public_job(job, profile)

    assert not any("sertifika" in item.casefold() for item in result["unknown_conditions"])


def test_p3_is_used_when_listing_accepts_p1_p2_and_p3():
    profile = build_candidate_profile()
    job = {"title": "Uzman", "education_requirement": "Lisans Bilgisayar Mühendisliği", "kpss_score_type": "P1/P2/P3", "kpss_min_score": 80, "description": "YDS puanı en az 70 olmalıdır."}
    result = classify_public_job(job, profile)
    assert "P3 puanınız 87.60" in result["reason"]
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"
    assert any("YDS" in item for item in result["unknown_conditions"])


def test_unknown_yds_requirement_is_potential():
    profile = build_candidate_profile()
    job = {"title": "Bilgisayar Mühendisi", "education_requirement": "Lisans Bilgisayar Mühendisliği", "kpss_score_type": "P3", "kpss_min_score": 80, "description": "İngilizce YDS puanı en az 70 olmalıdır."}
    result = classify_public_job(job, profile)
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"
    assert any("YDS" in item for item in result["unknown_conditions"])


def test_explicit_department_mismatch_is_not_eligible():
    profile = build_candidate_profile()
    job = {"title": "Uzman", "education_requirement": "Hukuk Fakültesi mezunu olmak", "kpss_score_type": "P3", "kpss_min_score": 80, "description": ""}
    assert classify_public_job(job, profile)["category"] == "UYGUN DEĞİL"


def test_4001_matches_a_bachelor_degree():
    profile = build_candidate_profile()
    job = {"title": "Memur", "education_requirement": "", "qualification_codes": "4001", "description": ""}
    result = classify_public_job(job, profile)
    assert "4001" in result["qualification_codes"]
    assert any("4001" in reason for reason in result["reason"].split("."))
    assert result["category"] == "UYGUN"


def test_unverified_4531_stays_potential_not_assumed():
    profile = build_candidate_profile()
    job = {"title": "Programcı", "education_requirement": "Bilgisayar Mühendisliği Lisans", "qualification_codes": "4531", "description": ""}
    result = classify_public_job(job, profile)
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"
    assert any("4531" in item for item in result["unknown_conditions"])


def test_unknown_mandatory_condition_is_never_assumed_failed():
    profile = build_candidate_profile()
    job = {"title": "Uzman", "education_requirement": "Lisans Bilgisayar Mühendisliği", "kpss_score_type": "P3", "kpss_min_score": 80, "description": "Sürücü belgesine sahip olmak zorunludur."}
    result = classify_public_job(job, profile)
    assert result["category"] == "POTANSİYEL OLARAK UYGUN"
    assert any("Sürücü belgesi" in item for item in result["unknown_conditions"])
