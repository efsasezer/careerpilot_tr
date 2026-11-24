"""Sonuç takibi, YLSY duyuruları ve Kariyer Kapısı hesap aktarımı testleri (ağ kullanılmaz)."""

from datetime import date, datetime, timedelta
import json

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import kk_account, notifications, results, ylsy
from backend.database import Base
from backend.events import extract_events
from backend.models import (
    AccountApplication, Announcement, CandidateProfile, Job, Notification, ResultAnnouncement, ResultTracking, UserJobState,
)

TODAY = date(2026, 11, 24)


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _job(**overrides):
    data = dict(
        sector="public", title="25 Sözleşmeli Personel Alım İlanı", organization="Örnek Üniversitesi Rektörlüğü",
        source_name="SBB Kamu İlanları", source_url="https://kamuilan.sbb.gov.tr/", application_start=date(2026, 11, 2),
        application_deadline=date(2026, 11, 16),
        description="Başvurular 02.11.2026 - 16.11.2026 tarihleri arasında yapılır. "
                    "Sonuçlar www.ornek.edu.tr adresinde ilan edilecektir.",
    )
    data.update(overrides)
    return Job(**data)


def _html(*links):
    filler = "".join(f'<a href="/sayfa/{i}">Menü bağlantısı {i}</a>' for i in range(12))
    return ("<html><body>" + filler + "".join(f'<a href="{href}">{text}</a>' for href, text in links) + "</body></html>").encode()


class FakeSite:
    """SiteReader için sahte ağ: adres → HTML; listede olmayan adres 404 döner."""

    def __init__(self, pages, failure=None, robots=None):
        self.pages, self.failure, self.robots, self.requested = pages, failure, robots, []

    def __call__(self, url):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            if self.robots is None:
                return {"status": 404, "url": url, "content_type": "text/html", "body": b"", "encoding": "utf-8"}
            return {"status": 200, "url": url, "content_type": "text/plain", "body": self.robots.encode(), "encoding": "utf-8"}
        if self.failure:
            raise self.failure
        body = self.pages.get(url.rstrip("/")) or self.pages.get(url)
        if body is None:
            return {"status": 404, "url": url, "content_type": "text/html", "body": b"", "encoding": "utf-8"}
        return {"status": 200, "url": url, "content_type": "text/html; charset=utf-8", "body": body, "encoding": "utf-8"}


def _reader(pages, **kwargs):
    return results.SiteReader(fetch=FakeSite(pages, **kwargs), delay=0)


def _check(db, pages, **kwargs):
    return results.check_results(db, today=TODAY, reader=_reader(pages, **kwargs))


def _status(db, job, tracking=""):
    return results.job_result_status(db, job, tracking, today=TODAY)


DETAIL = ("<html><body><h1>Sözleşmeli Personel Alımı Sonuçları</h1><p>Yayın Tarihi: 20.11.2026</p>"
          "<p>02.11.2026 tarihli ilanımıza ilişkin sonuçlar ektedir.</p><a href='/dosya/sonuc.pdf'>Sonuç listesi</a></body></html>").encode()


# ---------------------------------------------------------------------------
# 1. İlan metninden sonuç tarihi
# ---------------------------------------------------------------------------

def test_result_dates_are_read_from_label_style_text():
    text = ("Başvuru Başlangıç Tarihi 07.11.2026 Son Başvuru Tarihi 20.11.2026 "
            "Ön Değerlendirme Sonucu Açıklanma Tarihi 27.11.2026 Giriş Sınavı Tarihi 01.12.2026 "
            "Nihai Değerlendirme Sonucu Açıklanma Tarihi 04.12.2026")
    events = [(e["date"], e["title"]) for e in extract_events(text, today=TODAY) if e["kind"] == "result"]
    assert events == [(date(2026, 11, 27), "Ön değerlendirme sonucu"), (date(2026, 12, 4), "Nihai sonuç")]


def test_result_date_is_not_invented_when_text_has_none():
    assert extract_events("Sonuçlar kurumumuz internet sitesinde ilan edilecektir.", today=TODAY) == []


def test_official_source_comes_from_the_result_sentence():
    source = results.official_source(
        "Başvurular kariyerkapisi.gov.tr üzerinden yapılır. Bilgi için ik@ornek.edu.tr. Sonuçlar https://personel.ornek.edu.tr/duyurular adresinde ilan edilecektir."
    )
    assert source["url"] == "https://personel.ornek.edu.tr/duyurular"
    assert results.official_source("Başvurular Kariyer Kapısı üzerinden alınır.")["url"] == ""


# ---------------------------------------------------------------------------
# 2-3. Sonuç duyurusunun bulunması ve doğru ilanla eşleşmesi
# ---------------------------------------------------------------------------

def test_result_is_found_on_official_site_and_matched():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    pages = {
        "https://www.ornek.edu.tr": _html(("/duyuru/42", "Sözleşmeli Personel Alımı Sonuçları 20.11.2026"), ("/duyuru/7", "Yatay Geçiş Sonuçları")),
        "https://www.ornek.edu.tr/duyuru/42": DETAIL,
    }
    report = _check(db, pages)
    assert report["found"] == 1 and report["errors"] == 0
    row = db.scalar(select(ResultAnnouncement))
    assert (row.job_id, row.match_status, row.published_date) == (job.id, "matched", date(2026, 11, 20))
    assert row.url == "https://www.ornek.edu.tr/duyuru/42" and row.document_url.endswith("/dosya/sonuc.pdf")
    status = _status(db, job)
    assert status["status"] == "found" and status["announcements"][0]["url"] == row.url


def test_results_of_another_recruitment_are_not_attached():
    db = _database()
    db.add(_job())
    db.commit()
    pages = {"https://www.ornek.edu.tr": _html(
        ("/d/1", "67 Sözleşmeli Personel Alımı Sözlü Sınav Sonuçları"),       # kişi sayısı farklı
        ("/d/2", "Öğretim Görevlisi Alımı Nihai Değerlendirme Sonuçları"),     # kadro türü farklı
        ("/d/3", "2025 Yılı Sözleşmeli Personel Alımı Sonuçları"),             # önceki yıl
        ("/d/4", "Sözleşmeli Personel Alımı Sonuçları 05.10.2026"),            # ilandan önce yayımlanmış
    )}
    assert _check(db, pages)["found"] == 0
    assert db.scalar(select(ResultAnnouncement)) is None


def test_ambiguous_match_between_two_jobs_needs_review():
    db = _database()
    first = _job(title="Sözleşmeli Personel Alım İlanı")
    second = _job(title="Sözleşmeli Personel Alım İlanı (Sağlık)", source_name="İlan.gov.tr", application_start=date(2026, 11, 3), application_deadline=date(2026, 11, 17))
    db.add_all([first, second])
    db.commit()
    pages = {"https://www.ornek.edu.tr": _html(("/d/9", "Sözleşmeli Personel Alımı Sonuçları 20.11.2026"))}
    _check(db, pages)
    rows = db.scalars(select(ResultAnnouncement)).all()
    assert rows and all(row.match_status == "needs_review" for row in rows)
    assert _status(db, first)["status"] == "needs_review"
    assert "doğrulanmalı" in _status(db, first)["message"]


def test_unrelated_dates_in_page_sidebar_are_not_evidence():
    profile = results.job_profile(_job(title="Uzman Yardımcısı Alım İlanı"), [], [])
    scored = results.score_candidate(profile, "Uzman Yardımcısı Alımı Nihai Sonuçları", "İlgili Haberler\nPazartesi, 16 Kasım 2026\n", None, TODAY)
    assert scored is not None and scored["confident"] is False


# ---------------------------------------------------------------------------
# 4-5. Sonuç yokken ve kaynak okunamadığında durum
# ---------------------------------------------------------------------------

def test_no_result_yet_is_reported_as_checked_not_found():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    report = _check(db, {"https://www.ornek.edu.tr": _html(("/d/1", "Yemek listesi"))})
    assert report["checked"] == 1 and report["found"] == 0
    status = _status(db, job)
    assert status["status"] == "not_found" and "henüz resmî sonuç duyurusu bulunamadı" in status["message"]
    assert status["last_checked_at"]


def test_unreachable_source_is_not_reported_as_no_result():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    report = _check(db, {}, failure=requests.ConnectionError("down"))
    assert report["errors"] == 1 and report["checked"] == 0
    status = _status(db, job)
    assert status["status"] == "error" and "Kaynak kontrol edilemedi" in status["message"]
    assert "bulunamadı" not in status["message"]
    assert db.get(ResultTracking, job.id).last_success_at is None


def test_javascript_only_site_and_robots_block_count_as_errors():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    _check(db, {"https://www.ornek.edu.tr": b"<html><body><div id='app'></div></body></html>"})
    assert _status(db, job)["status"] == "error"
    blocked = FakeSite({"https://www.ornek.edu.tr": _html(("/d/1", "Sözleşmeli Personel Alımı Sonuçları"))}, robots="User-agent: *\nDisallow: /")
    results.check_results(db, today=TODAY, reader=results.SiteReader(fetch=blocked, delay=0))
    assert "robots.txt" in db.get(ResultTracking, job.id).detail
    assert [url for url in blocked.requested if not url.endswith("robots.txt")] == []


def test_job_without_official_address_and_open_job_are_distinguished():
    db = _database()
    no_source = _job(description="Başvurular Kariyer Kapısı üzerinden yapılır. Sonuçlar Kariyer Kapısı üzerinden görüntülenir.")
    still_open = _job(title="Başka Alım", organization="Başka Kurum", application_deadline=TODAY + timedelta(days=5))
    db.add_all([no_source, still_open])
    db.commit()
    report = _check(db, {})
    assert report["tracked"] == 1 and report["no_source"] == 1
    status = _status(db, no_source)
    assert status["status"] == "no_source" and status["account_only"] is True
    assert _status(db, still_open)["status"] == "waiting"


# ---------------------------------------------------------------------------
# 6. Bildirimler: yinelenme yok, her aşama ayrı, eski aşamalar korunur
# ---------------------------------------------------------------------------

def test_each_result_stage_notifies_once_and_history_is_kept():
    db = _database()
    job = _job()
    db.add(job)
    db.flush()
    db.add(UserJobState(job_id=job.id, tracking="applied", notes="", updated_at=datetime.now()))
    db.add(CandidateProfile(id=1, degree="Lisans", department="Bilgisayar Mühendisliği"))
    db.commit()
    first = {"https://www.ornek.edu.tr": _html(("/duyuru/42", "Sözleşmeli Personel Alımı Sonuçları 20.11.2026")),
             "https://www.ornek.edu.tr/duyuru/42": DETAIL}
    _check(db, first)
    notifications.generate_notifications(db)
    _check(db, first)
    notifications.generate_notifications(db)
    assert len(db.scalars(select(Notification).where(Notification.kind == "result")).all()) == 1

    second = dict(first)
    second["https://www.ornek.edu.tr"] = _html(
        ("/duyuru/42", "Sözleşmeli Personel Alımı Sonuçları 20.11.2026"),
        ("/duyuru/55", "Sözleşmeli Personel Alımı Asil ve Yedek Aday Listesi 23.11.2026"),
    )
    second["https://www.ornek.edu.tr/duyuru/55"] = DETAIL.replace(b"20.11.2026", b"23.11.2026")
    _check(db, second)
    notifications.generate_notifications(db)
    kinds = [row.kind for row in db.scalars(select(ResultAnnouncement).order_by(ResultAnnouncement.id)).all()]
    assert kinds == ["result", "list"]
    assert len(db.scalars(select(Notification).where(Notification.kind == "result")).all()) == 2


def test_user_rejection_survives_rechecks():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    pages = {"https://www.ornek.edu.tr": _html(("/duyuru/42", "Sözleşmeli Personel Alımı Sonuçları 20.11.2026")),
             "https://www.ornek.edu.tr/duyuru/42": DETAIL}
    _check(db, pages)
    row = db.scalar(select(ResultAnnouncement))
    row.user_decision = "rejected"
    db.commit()
    _check(db, pages)
    assert len(db.scalars(select(ResultAnnouncement)).all()) == 1
    assert db.scalar(select(ResultAnnouncement)).user_decision == "rejected"
    assert _status(db, job)["status"] == "not_found"


# ---------------------------------------------------------------------------
# YLSY
# ---------------------------------------------------------------------------

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>2026 Y\xc4\xb1l\xc4\xb1 1416 Burslar\xc4\xb1 Ba\xc5\x9fvuru Duyurusu</title><link>https://yyegm.meb.gov.tr/www/x/icerik/1300</link><pubDate>Mon, 14 Dec 2026 10:00:00 +0300</pubDate></item>
<item><title>Genel M\xc3\xbcd\xc3\xbcr\xc3\xbcm\xc3\xbcz konferansa kat\xc4\xb1ld\xc4\xb1</title><link>https://yyegm.meb.gov.tr/www/y/icerik/1301</link><pubDate>Mon, 14 Dec 2026 11:00:00 +0300</pubDate></item>
</channel></rss>"""
PAGE = ("<html><head><title>2026 Yılı 1416 Bursları Başvuru Duyurusu</title></head><body><span>Yayın : 14.12.2026 10:00</span>"
        "<div class=\"content article-detay\"><p>Başvurular REBUS üzerinden alınacaktır.</p>"
        "<a href=\"/meb_iys_dosyalar/2026_12/duyuru.pdf\">Duyuru metni</a></div></body></html>").encode()


def _ylsy_fetch(calls):
    def fetch(url):
        calls.append(url)
        if url == ylsy.RSS_URL:
            return RSS
        if url.endswith("/icerik/1300"):
            return PAGE
        raise RuntimeError("HTTP 404")
    return fetch


def test_ylsy_announcements_are_added_once_and_notified_once(monkeypatch):
    monkeypatch.setattr(ylsy.time, "sleep", lambda _: None)
    db = _database()
    db.add(Announcement(topic="ylsy", url="https://yyegm.meb.gov.tr/www/x/icerik/1094", title="2025 Yılı 1416 Bursları Başvuru ve Tercih Kılavuzu",
                        category="guide", facts='{"cycle": 2025, "backfill": true}', first_seen_at=datetime.now()))
    db.commit()
    calls: list[str] = []
    assert ylsy.sync_ylsy(db, fetch=_ylsy_fetch(calls))["new"] == 1
    assert ylsy.sync_ylsy(db, fetch=_ylsy_fetch(calls))["new"] == 0
    row = db.scalar(select(Announcement).where(Announcement.url.like("%1300")))
    assert row.published_date == date(2026, 12, 14) and json.loads(row.attachments)[0]["url"].endswith("duyuru.pdf")
    notifications.generate_notifications(db)
    notifications.generate_notifications(db)
    created = db.scalars(select(Notification).where(Notification.kind == "announcement")).all()
    assert len(created) == 1 and "1300" in created[0].body  # geçmiş (backfill) duyuru bildirim üretmez


def test_ylsy_source_failure_is_reported(monkeypatch):
    monkeypatch.setattr(ylsy.time, "sleep", lambda _: None)
    db = _database()
    db.add(Announcement(topic="ylsy", url="u", title="2025 1416", first_seen_at=datetime.now()))
    db.commit()

    def broken(url):
        raise RuntimeError("HTTP 503")

    report = ylsy.sync_ylsy(db, fetch=broken)
    assert report["status"] == "error" and "okunamadı" in report["error"]


def _guide(db):
    facts = {
        "cycle": 2025, "ales_min": {"value": 75, "evidence": "ALES puan türünden en az 75 almış olmak"},
        "ales_years": {"value": [2021, 2022, 2023, 2024, 2025], "evidence": "…"}, "gpa_min": {"value": 2.5, "evidence": "…"},
        "birth_year_min": {"value": {"master": 1995, "phd": 1992}, "evidence": "…"},
        "codes": {"3124": "Bilgisayar Mühendisliği", "9999": "Tarih"},
        "tables": [
            {"group_code": "2025105", "area_code": "1", "group": "YÖK", "institution": "A Üniversitesi", "field": "Yapay Zekâ", "quota": "1",
             "ales_types": ["EA", "SAY"], "codes": ["3124"], "level": "Sadece Doktora", "countries": "Almanya", "document": "t1"},
            {"group_code": "2025200", "area_code": "2", "group": "YÖK", "institution": "B Üniversitesi", "field": "Tarih", "quota": "1",
             "ales_types": ["EA", "SAY", "SÖZ"], "codes": ["9999"], "level": "Yüksek Lisans", "countries": "Fransa", "document": "t1"},
        ],
    }
    row = Announcement(topic="ylsy", url="g", title="2025 Yılı 1416 Bursları Başvuru ve Tercih Kılavuzu", category="guide",
                       facts=json.dumps(facts), first_seen_at=datetime.now())
    db.add(row)
    db.commit()
    return row


def test_ylsy_does_not_decide_without_verified_score_type():
    db = _database()
    guide = _guide(db)
    profile = CandidateProfile(id=1, department="Bilgisayar Mühendisliği", ales_score=87)
    outcome = ylsy.assess(profile, guide, TODAY)
    assert outcome["decision"] == "needs_verification"
    assert [field["field"] for field in outcome["fields"]] == ["Yapay Zekâ"]
    statuses = {check["name"]: check["status"] for check in outcome["checks"]}
    assert statuses["ALES puanı"] == "met" and statuses["ALES puan türü"] == "unknown"


def test_ylsy_decision_with_complete_profile():
    db = _database()
    guide = _guide(db)
    complete = dict(id=1, department="Bilgisayar Mühendisliği", ales_score=87, ales_year=2025, gpa=3.1, birth_date=date(1999, 5, 1))
    assert ylsy.assess(CandidateProfile(**complete, ales_score_type="sayisal"), guide, TODAY)["decision"] == "eligible"
    assert ylsy.assess(CandidateProfile(**complete, ales_score_type="sozel"), guide, TODAY)["decision"] == "not_eligible"
    low = ylsy.assess(CandidateProfile(**{**complete, "ales_score": 70}, ales_score_type="sayisal"), guide, TODAY)
    assert low["decision"] == "not_eligible"


def test_ylsy_guide_text_parsing_and_title_filter():
    text = ("1.2 Başvurularda 2021, 2022, 2023, 2024 ve 2025 yıllarında yapılan Akademik Personel ve Lisansüstü Eğitimi Giriş Sınavı (ALES) sonuçları geçerlidir. "
            "c. Lisans öğreniminde “4 üzerinden en az 2.50” not ortalamasına sahip olmak, ç. Tercih edilecek öğrenim alanına ait ALES puan türünden en az 75 almış olmak, "
            "Adaylar, başvurularını 19-30 Aralık 2025 tarihleri arasında REBUS üzerinden yapar.")
    facts = ylsy.parse_guide_text(text)
    assert facts["ales_min"]["value"] == 75 and facts["gpa_min"]["value"] == 2.5
    assert facts["ales_years"]["value"] == [2021, 2022, 2023, 2024, 2025]
    assert facts["application"]["start"] == "2025-12-19" and facts["application"]["end"] == "2025-12-30"
    assert "birth_year_min" not in facts  # metinde yoksa uydurulmaz
    assert ylsy.is_relevant("2025 Yılı 1416 Bursları Sözlü Sınav Sonuçları") and ylsy.is_relevant("2024 YLSY duyurusu")
    assert not ylsy.is_relevant("Öğretmen atama duyurusu")


# ---------------------------------------------------------------------------
# Kariyer Kapısı hesabı
# ---------------------------------------------------------------------------

def test_account_rows_are_normalized_matched_and_not_duplicated():
    db = _database()
    job = _job()
    db.add(job)
    db.commit()
    headers = ["Kurum", "İlan Adı", "Başvuru Tarihi", "Durum"]
    rows = [["Örnek Üniversitesi Rektörlüğü", "25 Sözleşmeli Personel Alım İlanı", "05.11.2026 14:20", "Başvuru Alındı"],
            ["Bilinmeyen Kurum", "Müfettiş Yardımcılığı Sınavı", "01.03.2026", "Değerlendirme"]]
    records = kk_account.normalize_rows("applications", headers, rows)
    assert records[0]["applied_date"] == date(2026, 11, 5) and records[0]["status"] == "Başvuru Alındı"
    assert kk_account.store_records(db, records)["new"] == 2
    again = kk_account.store_records(db, records)
    assert again["new"] == 0 and len(db.scalars(select(AccountApplication)).all()) == 2
    stored = {row.organization: row for row in db.scalars(select(AccountApplication)).all()}
    assert stored["Örnek Üniversitesi Rektörlüğü"].job_id == job.id
    assert stored["Bilinmeyen Kurum"].match_status == "unmatched"
    assert db.get(UserJobState, job.id).tracking == "applied"


def test_account_exam_rows_carry_date_time_and_place():
    records = kk_account.normalize_rows("exams", ["İlan", "Sınav Tarihi", "Sınav Yeri", "Sonuç"],
                                        [["Uzman Yardımcılığı", "12.12.2026 10:00", "Ankara", ""]])
    assert (records[0]["exam_date"], records[0]["exam_time"], records[0]["exam_place"]) == (date(2026, 12, 12), "10:00", "Ankara")


def test_account_overview_is_unverified_until_a_real_import():
    db = _database()
    overview = kk_account.overview(db)
    assert overview["verified"] is False and overview["items"] == []
