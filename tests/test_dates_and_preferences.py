"""Tarih çıkarımı, başvuru dönemi, bildirim tercihleri, ilan bazında susturma ve Türkiye saati testleri."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import clock, notifications, sync
from backend.database import Base
from backend.events import extract_events, sync_job_events
from backend.models import AppSetting, CandidateProfile, Job, JobDocument, JobEvent, Notification, UserJobState
from backend.schemas import NotificationSettings

TODAY = date(2026, 11, 26)


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _events(text):
    return {(event["kind"], event["date"].isoformat()) for event in extract_events(text, today=TODAY)}


# ---------------------------------------------------------------------------
# Tarih türleri birbirine karışmaz
# ---------------------------------------------------------------------------

def test_calendar_table_yields_one_event_per_label():
    text = ("İlan Yayım Tarihi 10.11.2026 Başvuru Başlangıç Tarihi 10.11.2026 Son Başvuru Tarihi 24.11.2026 "
            "Ön Değerlendirme Sonucu Açıklanma Tarihi 27.11.2026 Giriş Sınavı Tarihi 01.12.2026 "
            "Nihai Değerlendirme Sonucu Açıklanma Tarihi 04.12.2026")
    assert _events(text) == {("result", "2026-11-27"), ("exam", "2026-12-01"), ("result", "2026-12-04")}
    # Yayın ve başvuru tarihleri sınav ya da sonuç olarak takvime girmez.
    assert not {date_text for _, date_text in _events(text)} & {"2026-11-10", "2026-11-24"}


def test_exam_interview_result_and_start_dates_are_separate_events():
    text = ("Yazılı Sınav Tarihi ve Saati: 12 Aralık 2026 Cumartesi 10:00 Sözlü Sınav Tarihi: 20.12.2026 "
            "Sınav Sonuç Tarihi 25.12.2026 Göreve Başlama Tarihi 04.01.2027")
    found = {event["kind"]: event for event in extract_events(text, today=TODAY)}
    assert found["exam"]["date"] == date(2026, 12, 12) and found["exam"]["time"] == "10:00"
    assert found["interview"]["date"] == date(2026, 12, 20)
    assert found["result"]["date"] == date(2026, 12, 25)
    assert found["start_work"]["date"] == date(2027, 1, 4)
    assert all(event["method"] == "label" and event["confidence"] == "high" for event in found.values())


@pytest.mark.parametrize("text, expected", [
    ("Sınava girmeye hak kazanan adaylar KPSS puanları ile sınav yeri ve zamanı başvuruların değerlendirilmesini müteakip "
     "21.12.2026 tarihinde Belediyemizin web sayfası www.akhisar.bel.tr adresinde ilan edilecektir.", {("result", "2026-12-21")}),
    ("Sınav Giriş Tarihi : 24.12.2026", {("exam", "2026-12-24")}),
    ("Giriş Sınav Sonuçlarının İlan Tarihi : 18.12.2026", {("result", "2026-12-18")}),
    ("4- Giriş Sınavları 14.12.2026 tarihinde saat 14:00'da başvurulan birimlerde yapılacaktır.", {("exam", "2026-12-14")}),
    ("Memur alımı için, 18/12/2026 tarihinde saat: 10’da başlamak üzere Belediye Hizmet Binasında sözlü sınav yapılacaktır.", {("interview", "2026-12-18")}),
    ("Yarışma Sınavına (Mülakat) Katılmaya Hak Kazanan Adayların İlanı : 04/12/2026", {("result", "2026-12-04")}),
])
def test_real_announcement_sentences(text, expected):
    assert _events(text) == expected


@pytest.mark.parametrize("text", [
    "Sınav tarihi daha sonra duyurulacaktır.",
    "Sonuçlar kurumumuz internet sitesinde ilan edilecektir.",
    "657 sayılı Kanunun 48 inci maddesi 14.07.1965 tarihlidir.",
    "Adayların 01.01.1996 tarihinden sonra doğmuş olması gerekir.",
    "Sınava girecek adaylar sınav ücretini 16-22 Aralık 2026 tarihleri arasında yatıracaktır.",
])
def test_no_date_is_invented_or_taken_from_unrelated_context(text):
    assert extract_events(text, today=TODAY) == []


@pytest.mark.parametrize("text, expected", [
    ("1.Başvurular 03 Kasım 2026 tarihinde başlayıp, 04 Aralık 2026 tarihinde sona erecektir.", (date(2026, 11, 3), date(2026, 12, 4))),
    ("Sınav başvuruları 9 Kasım 2026 günü başlayıp 22 Kasım 2026 günü saat 23:59 itibarıyla sona erecektir.", (date(2026, 11, 9), date(2026, 11, 22))),
    ("Sınava ön başvurular, 1-7 Aralık 2026 tarihleri arasında olacaktır.", (date(2026, 12, 1), date(2026, 12, 7))),
    ("Adaylar başvurularını, 23 Kasım 2026 saat 10:00 - 30 Kasım 2026 saat 17:00 arasında yapacaklardır.", (date(2026, 11, 23), date(2026, 11, 30))),
    ("Başvurular 28 Aralık 2026 – 8 Ocak 2027 tarihleri arasında alınacaktır.", (date(2026, 12, 28), date(2027, 1, 8))),
    ("Son başvuru tarihi : 20.11.2026 mesai bitimidir.", (None, date(2026, 11, 20))),
    # Birden çok dönem sayan, ücret ya da sonuçtan söz eden cümlelerden tarih seçilmez.
    ("İlk Kez Katılacaklar İçin Başvuru Tarihleri :7 Eylül – 2 Ekim 2026 Tekrar Katılacaklar İçin Başvuru Tarihleri : 16 Kasım – 4 Aralık 2026", (None, None)),
    ("Adaylar ön başvuru ücretini 1-8 Aralık 2026 tarihleri arasında yatıracaklardır.", (None, None)),
    ("Başvuru sonuçları 10.12.2026 tarihine kadar ilan edilecektir.", (None, None)),
    ("Başvurular şahsen yapılacaktır.", (None, None)),
])
def test_worded_application_window(text, expected):
    assert sync.worded_application_window(text) == expected


def test_missing_deadline_is_backfilled_from_documents_without_overwriting_known_dates():
    db = _database()
    empty = Job(sector="public", title="Memur Alımı", organization="A Belediyesi", description="Memur alım ilanı. " * 10)
    known = Job(sector="public", title="İşçi Alımı", organization="B Belediyesi", application_deadline=date(2026, 12, 1),
                description="Başvurular 03 Kasım 2026 tarihinde başlayıp, 31 Aralık 2026 tarihinde sona erecektir. " * 3)
    db.add_all([empty, known])
    db.flush()
    db.add(JobDocument(job_id=empty.id, document_url="https://webdosya.csb.gov.tr/ilan.docx", status="read",
                       extracted_text="Başvurular 21.12.2026 - 25.12.2026 tarihleri arasında şahsen yapılacaktır."))
    db.commit()
    assert sync.backfill_application_dates(db) == 1
    assert (empty.application_start, empty.application_deadline) == (date(2026, 12, 21), date(2026, 12, 25))
    assert known.application_deadline == date(2026, 12, 1)


def test_rescan_does_not_duplicate_events_and_keeps_user_edits():
    db = _database()
    job = Job(sector="public", title="Memur Alımı", organization="A Kurumu", application_deadline=date(2026, 12, 10),
              description="Yazılı Sınav Tarihi: 20.12.2026 Sözlü Sınav Tarihi: 27.12.2026 " + "ilan metni " * 20)
    db.add(job)
    db.commit()
    sync_job_events(db, job, today=TODAY)
    db.commit()
    first = sorted((event.kind, event.event_date) for event in db.scalars(select(JobEvent)).all())
    exam = db.scalar(select(JobEvent).where(JobEvent.kind == "exam"))
    exam.event_date, exam.user_edited = date(2026, 12, 21), True  # kullanıcı tarihi düzeltti
    db.commit()
    sync_job_events(db, job, today=TODAY)
    sync_job_events(db, job, today=TODAY)
    db.commit()
    again = sorted((event.kind, event.event_date) for event in db.scalars(select(JobEvent)).all())
    assert len(again) == len(first) == 3
    assert ("exam", date(2026, 12, 21)) in again and ("exam", date(2026, 12, 20)) not in again


# ---------------------------------------------------------------------------
# Bildirim tercihleri ve ilan bazında susturma
# ---------------------------------------------------------------------------

def _job_with_exam(db, title, organization):
    today = clock.today()
    job = Job(sector="public", title=title, organization=organization, source_name="SBB Kamu İlanları",
              application_start=today - timedelta(days=20), application_deadline=today - timedelta(days=2),
              description="Herhangi bir lisans programından mezun olmak. " * 4)
    db.add(job)
    db.flush()
    db.add(UserJobState(job_id=job.id, tracking="applied", notes="", updated_at=clock.now()))
    db.add(JobEvent(job_id=job.id, kind="exam", event_date=today + timedelta(days=2), source="auto", updated_at=clock.now()))
    db.add(JobEvent(job_id=job.id, kind="result", event_date=today + timedelta(days=3), source="auto", updated_at=clock.now()))
    return job


def _kinds(db):
    return sorted(row.title.split(":")[1].split("—")[0].strip() for row in db.scalars(
        select(Notification).where(Notification.kind == "event_upcoming")).all())


def test_reminders_follow_user_preferences_and_per_job_mute():
    db = _database()
    db.add(CandidateProfile(id=1, degree="Lisans", department="İşletme"))
    first = _job_with_exam(db, "5 Memur Alımı", "A Kurumu")
    second = _job_with_exam(db, "3 Uzman Alımı", "B Kurumu")
    db.get(UserJobState, second.id).muted = True  # bu ilanın bildirimleri kapalı
    db.add(AppSetting(key="notifications", value=NotificationSettings(remind_result=False).model_dump_json()))
    db.commit()
    notifications.refresh_daily(db)
    rows = db.scalars(select(Notification).where(Notification.kind == "event_upcoming")).all()
    assert [row.job_id for row in rows] == [first.id]  # susturulan ilan için hatırlatma yok
    assert "Sınav" in rows[0].title  # sonuç hatırlatması kapalı, sınav hatırlatması açık
    notifications.refresh_daily(db)
    assert len(db.scalars(select(Notification).where(Notification.kind == "event_upcoming")).all()) == 1  # yinelenmez

    db.get(UserJobState, second.id).muted = False  # yeniden açıldı
    db.commit()
    notifications.refresh_daily(db)
    assert {row.job_id for row in db.scalars(select(Notification).where(Notification.kind == "event_upcoming")).all()} == {first.id, second.id}


def test_settings_saved_before_new_preferences_keep_working():
    old = NotificationSettings(**{"notify_categories": ["UYGUN"], "deadline_reminder_days": 5})
    assert old.remind_exam and old.remind_deadline and old.notify_results  # yeni alanlar varsayılan olarak açık


# ---------------------------------------------------------------------------
# Türkiye saati
# ---------------------------------------------------------------------------

def test_today_is_turkey_date_even_when_server_clock_is_utc(monkeypatch):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # sunucu saati: 26 Kasım 22:30 UTC = Türkiye'de 27 Kasım 01:30
            moment = datetime(2026, 11, 26, 22, 30, tzinfo=timezone.utc)
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    monkeypatch.setattr(clock, "datetime", _Frozen)
    assert clock.today() == date(2026, 11, 27)
    assert clock.now() == datetime(2026, 11, 27, 1, 30)


# ---------------------------------------------------------------------------
# KPSS yılı ayrı bir şarttır
# ---------------------------------------------------------------------------

def _kpss_year_status(text, **profile):
    from backend.eligibility import build_candidate_profile, classify_public_job

    candidate = build_candidate_profile({"degree": "Lisans", "department": "İşletme", "kpss_scores": {"P3": 80}, **profile})
    job = {"title": "Memur Alımı", "organization": "Kurum", "description": text}
    found = {item["name"]: item for item in classify_public_job(job, candidate)["requirements"]}
    return found.get("KPSS yılı", {}).get("status"), found.get("KPSS", {}).get("status")


def test_kpss_year_is_checked_separately_from_score():
    text = ("Herhangi bir lisans programından mezun olmak. ÖSYM tarafından 2026 yılında yapılan Kamu Personel Seçme Sınavı (B) grubundan "
            "KPSS P3 puan türünden en az 70 puan almış olmak. ") * 2
    assert _kpss_year_status(text) == ("unknown", "met")             # yıl profilde yok: doğrulanmalı
    assert _kpss_year_status(text, kpss_year=2026) == ("met", "met")
    assert _kpss_year_status(text, kpss_year=2024) == ("not_met", "met")
    both = text.replace("2026 yılında yapılan", "2025 veya 2026 yılında yapılan")
    assert _kpss_year_status(both, kpss_year=2025) == ("met", "met")
    without_year = text.replace("2026 yılında yapılan ", "")
    assert _kpss_year_status(without_year, kpss_year=2024)[0] is None  # ilan yıl yazmıyorsa şart üretilmez
