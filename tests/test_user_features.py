"""Giriş, elle doğrulama, tarih çıkarımı, OCR ve gerçek ilan metniyle uygunluk testleri."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import auth, main, notifications
from backend.database import Base, SessionLocal
from backend.eligibility import build_candidate_profile, classify_public_job
from backend.events import extract_events, sync_job_events, task_occurs_on
from backend.matching import build_matches, decompose_job_positions
from backend.models import (
    CandidateProfile, DocumentPosition, Job, JobDocument, JobEvent, Notification, UserJobState, UserTask, UserVerification,
)
from backend.schemas import TrackingUpdate, VerificationUpdate

UYGUN, POTANSIYEL, DEGIL = "UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "karsiyaka_memur_alimi.json").read_text(encoding="utf-8"))


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _job(**overrides):
    data = dict(
        sector="public", title="5 Memur Alacak", organization="Örnek Belediye Başkanlığı", source_name="SBB Kamu İlanları",
        source_url="https://kamuilan.sbb.gov.tr/", application_start=date.today() - timedelta(days=2),
        application_deadline=date.today() + timedelta(days=5),
        description="Herhangi bir lisans programından mezun olmak. KPSS P3 puan türünden en az 60 puan almış olmak. " * 3,
    )
    data.update(overrides)
    return Job(**data)


def _engineer(**overrides):
    data = {"degree": "Lisans", "department": "Bilgisayar Mühendisliği", "kpss_scores": {"P3": 87.66}}
    data.update(overrides)
    return build_candidate_profile(data)


# ---------------------------------------------------------------------------
# Giriş ve oturum
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("CAREERPILOT_PASSWORD", "dogru-sifre-123")
    monkeypatch.setenv("CAREERPILOT_SESSION_SECRET", "x" * 40)
    auth.login_limiter.reset()
    with TestClient(main.app) as test_client:
        yield test_client
    auth.login_limiter.reset()


def test_everything_except_health_requires_a_session(client):
    assert client.get("/health").status_code == 200
    assert client.get("/auth/me").json() == {"authenticated": False, "config_error": None}
    for method, path in (("get", "/matches"), ("get", "/profile"), ("post", "/sync"), ("patch", "/jobs/1/tracking"), ("post", "/tasks")):
        assert getattr(client, method)(path).status_code == 401  # okuma da yazma da oturumsuz reddedilir


def test_login_sets_httponly_cookie_and_logout_invalidates_it_on_the_server(client):
    assert client.post("/auth/login", json={"password": "yanlis"}).status_code == 401
    response = client.post("/auth/login", json={"password": "dogru-sifre-123"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "dogru-sifre" not in cookie
    assert client.get("/profile").status_code == 200

    stolen = client.cookies.get(auth.COOKIE_NAME)
    assert client.post("/auth/logout").status_code == 200
    client.cookies.set(auth.COOKIE_NAME, stolen)  # eski çerez artık sunucuda geçersiz
    assert client.get("/profile").status_code == 401
    client.cookies.set(auth.COOKIE_NAME, stolen[:-3] + "abc")  # imzası bozuk çerez
    assert client.get("/profile").status_code == 401


def test_cookie_is_secure_behind_the_https_proxy(client):
    response = client.post("/auth/login", json={"password": "dogru-sifre-123"}, headers={"x-forwarded-proto": "https"})
    assert "secure" in response.headers["set-cookie"].lower()


def test_wrong_password_attempts_are_rate_limited(client):
    for _ in range(auth.MAX_FAILURES):
        assert client.post("/auth/login", json={"password": "yanlis"}).status_code == 401
    blocked = client.post("/auth/login", json={"password": "dogru-sifre-123"})  # doğru şifre de bekler
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


def test_missing_configuration_never_opens_access(monkeypatch):
    monkeypatch.delenv("CAREERPILOT_PASSWORD", raising=False)
    monkeypatch.setenv("CAREERPILOT_SESSION_SECRET", "x" * 40)
    with TestClient(main.app) as test_client:
        assert test_client.get("/matches").status_code == 503
        response = test_client.post("/auth/login", json={"password": ""})
        assert response.status_code in (422, 503)
        assert "CAREERPILOT_PASSWORD" in test_client.get("/auth/me").json()["config_error"]


def test_cross_site_write_is_rejected(client):
    client.post("/auth/login", json={"password": "dogru-sifre-123"})
    response = client.post("/tasks", json={"title": "x", "task_date": "2026-12-01"}, headers={"origin": "https://kotu-site.example"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Uygunluk: gerçek ilan metni ve kurallar
# ---------------------------------------------------------------------------

def test_karsiyaka_notice_every_row_is_evaluated_on_its_own_requirements():
    """İzmir Karşıyaka Belediyesi memur alım ilanı (resmî PDF'ten okunan gerçek metin)."""
    job = Job(id=1, title=FIXTURE["title"], organization=FIXTURE["organization"], description=FIXTURE["description"],
              application_deadline=date.fromisoformat(FIXTURE["application_deadline"]))
    document = JobDocument(id=1, job_id=1, document_url="https://x.gov.tr/a.pdf", shared_requirements=FIXTURE["shared_requirements"])
    rows = [DocumentPosition(document_id=1, **row) for row in FIXTURE["rows"]]
    positions = decompose_job_positions(job, [document], {1: rows})
    assert len(positions) == len(FIXTURE["rows"]) >= 1

    for position in positions:
        engineer = classify_public_job(position, _engineer())
        education = next(item for item in engineer["requirements"] if item["name"] == "Eğitim")
        # Kadro belirli bölümleri sayıyor (maliye, işletme, iktisat…); Bilgisayar Mühendisliği listede yok.
        assert education["status"] == "not_met" and "maliye" in education["evidence"].casefold()
        assert engineer["category"] == DEGIL
        assert next(item for item in engineer["requirements"] if item["name"] == "KPSS")["status"] == "met"

        economist = classify_public_job(position, build_candidate_profile(
            {"degree": "Lisans", "department": "İktisat", "kpss_scores": {"P3": 75}}))
        assert next(item for item in economist["requirements"] if item["name"] == "Eğitim")["status"] == "met"
        # "Sertifika VEYA okulda bilgisayar dersi": tek seçenek zorunluymuş gibi yorumlanmaz, doğrulamaya bırakılır.
        assert economist["category"] == POTANSIYEL
        assert any(item["name"] == "Bilgisayar belgesi" and item["status"] == "unknown" for item in economist["requirements"])


def test_general_degree_requirement_is_met_regardless_of_department():
    for wording in ("Herhangi bir lisans programından mezun olmak.", "En az lisans mezunu olmak."):
        result = classify_public_job({"title": "Memur", "description": wording + " KPSS P3 puan türünden en az 70 puan almış olmak."}, _engineer())
        assert result["category"] == UYGUN, wording
    specific = classify_public_job({"title": "Memur", "description": "Hukuk veya Maliye bölümünden mezun olmak."}, _engineer())
    assert specific["category"] == DEGIL


def test_alternatives_joined_with_or_are_not_all_required():
    text = "İnşaat Mühendisliği veya Bilgisayar Mühendisliği bölümlerinin birinden mezun olmak."
    assert classify_public_job({"title": "Mühendis", "description": text}, _engineer())["education"]["status"] == "met"


def test_preferred_experience_is_not_mandatory_and_missing_profile_fields_are_unknown():
    preferred = "Herhangi bir lisans programından mezun olmak. Tercihen en az 3 yıl deneyim sahibi olmak."
    assert classify_public_job({"title": "Memur", "description": preferred}, _engineer())["category"] == UYGUN

    required = "Herhangi bir lisans programından mezun olmak. Alanında en az 3 yıl mesleki deneyim sahibi olmak."
    assert classify_public_job({"title": "Uzman", "description": required}, _engineer())["category"] == POTANSIYEL
    assert classify_public_job({"title": "Uzman", "description": required}, _engineer(experience_state="none"))["category"] == DEGIL
    experienced = _engineer(experiences=[{"start": "2020-01", "end": "2024-01"}])
    assert classify_public_job({"title": "Uzman", "description": required}, experienced)["category"] == UYGUN


def test_age_is_measured_on_the_application_date_and_absent_conditions_are_marked_not_required():
    text = "Herhangi bir lisans programından mezun olmak. Başvuru tarihi itibarıyla 30 yaşını doldurmamış olmak."
    born = _engineer(birth_date="1997-01-10")
    before = classify_public_job({"title": "Memur", "description": text, "reference_date": date(2026, 12, 20)}, born)
    after = classify_public_job({"title": "Memur", "description": text, "reference_date": date(2027, 2, 1)}, born)
    assert before["category"] == UYGUN and after["category"] == DEGIL
    statuses = {item["name"]: item["status"] for item in before["requirements"]}
    assert statuses["Yaş"] == "met" and statuses["YDS"] == "not_required" and statuses["Deneyim"] == "not_required"
    assert next(item for item in before["requirements"] if item["name"] == "Yaş")["evidence"].startswith("Başvuru tarihi")


def test_preferences_never_change_official_eligibility():
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="Bilgisayar Mühendisliği", kpss_scores='{"P3": 87}',
                                preferences=json.dumps({"cities": ["Ankara"], "excluded": []})))
        db.add(_job(organization="İzmir Örnek Belediye Başkanlığı", city="İzmir"))
        db.commit()
        item = build_matches(db, full=False)["jobs"][0]
        assert item["category"] == UYGUN and item["out_of_preference"] is True


# ---------------------------------------------------------------------------
# Elle doğrulama
# ---------------------------------------------------------------------------

def test_manual_decision_overrides_system_and_survives_recalculation_and_rescan():
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="Bilgisayar Mühendisliği", kpss_scores='{"P3": 87}'))
        db.add(_job(description="Tablo 1'de belirtilen bölümlerden mezun olmak. KPSS P3 puan türünden en az 60 puan almış olmak. " * 2))
        db.commit()
        assert build_matches(db, full=False)["counts"][POTANSIYEL] == 1

        main.set_verification(1, VerificationUpdate(decision="eligible", note="Tabloya baktım"), db=db)
        result = build_matches(db, full=False)
        item = result["jobs"][0]
        assert result["counts"][UYGUN] == 1 and result["counts"][POTANSIYEL] == 0  # sayaçlar anında güncellenir
        assert item["system_category"] == POTANSIYEL and item["category"] == UYGUN
        assert item["verification"]["decision"] == "eligible" and item["verification"]["note"] == "Tabloya baktım"
        assert item["verification"]["stale"] is False and item["review_required"] is False

        # Profil değişir, sistem kararı değişir: kullanıcının kararı aynen kalır.
        profile = db.get(CandidateProfile, 1)
        profile.kpss_scores, profile.updated_at = '{"P3": 40}', datetime.now()
        db.commit()
        item = build_matches(db, full=False)["jobs"][0]
        assert item["system_category"] == DEGIL and item["category"] == UYGUN

        # İlan yeniden taranır ve tarihi değişir: karar silinmez, yalnızca uyarı çıkar.
        job = db.get(Job, 1)
        job.application_deadline = job.application_deadline + timedelta(days=7)
        job.updated_at = datetime.now()
        db.commit()
        item = build_matches(db, full=False)["jobs"][0]
        assert item["category"] == UYGUN and item["verification"]["stale"] is True
        assert any("son başvuru tarihi" in change for change in item["verification"]["changes"])
        assert db.scalar(select(UserVerification)).decision == "eligible"
        notifications.refresh_daily(db)
        assert any(n.kind == "verification_stale" for n in db.scalars(select(Notification)).all())

        main.acknowledge_update(1, db=db)  # "Gözden geçirdim, karar geçerli"
        item = build_matches(db, full=False)["jobs"][0]
        assert item["verification"]["stale"] is False and item["category"] == UYGUN

        main.set_verification(1, VerificationUpdate(decision="not_eligible"), db=db)  # Uygun ↔ Uygun değil
        assert build_matches(db, full=False)["jobs"][0]["category"] == DEGIL
        main.clear_verification(1, db=db)  # geri al: sistemin kararına döner
        item = build_matches(db, full=False)["jobs"][0]
        assert item["verification"] is None and item["category"] == item["system_category"] == DEGIL


def test_position_level_decision_makes_the_notice_eligible():
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="Bilgisayar Mühendisliği", kpss_scores='{"P3": 87}'))
        db.add(_job(description="Kadrolar tabloda belirtilmiştir."))
        db.add(JobDocument(id=1, job_id=1, document_url="https://x.gov.tr/a.pdf"))
        for index, title in enumerate(("Memur", "Tekniker"), 1):
            db.add(DocumentPosition(document_id=1, row_index=index, position_title=title, quota="1", kpss_score_type="P3",
                                    education_requirement="Hukuk bölümünden mezun olmak.", requirements_text="Hukuk bölümünden mezun olmak."))
        db.commit()
        items = build_matches(db, full=False)["jobs"]
        assert [item["category"] for item in items] == [DEGIL, DEGIL]
        main.set_verification(1, VerificationUpdate(decision="eligible", position_id=items[0]["id"]), db=db)
        items = build_matches(db, full=False)["jobs"]
        assert [item["category"] for item in items] == [UYGUN, DEGIL]
        assert items[0]["verification"]["scope"] == "position" and items[1]["verification"] is None


def test_tracking_lives_in_user_table_and_rescans_do_not_touch_it(monkeypatch):
    class Source:
        source_name = "SBB Kamu İlanları"
        pages_checked = 1

        def fetch_listings(self):
            return [{"detail_url": "https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=1", "external_id": "a", "user_url": "https://kamuilan.sbb.gov.tr/",
                     "title": "5 Memur Alacak", "institution": "Örnek Belediye Başkanlığı", "content_hash": "v1",
                     "application_end_date": date.today() + timedelta(days=9)}]

        def fetch_detail(self, _url):
            return {"source_text": "Herhangi bir lisans programından mezun olmak. " * 4, "content_hash": "d"}

    monkeypatch.setattr(main, "get_source_registry", lambda: {"sbb": Source()})
    with _database() as db:
        main.sync_all_sources(db)
        main.update_tracking(1, TrackingUpdate(tracking="applied", notes="Dilekçe hazır"), db=db)
        main.set_verification(1, VerificationUpdate(decision="eligible"), db=db)
        main.sync_all_sources(db)
        state = db.get(UserJobState, 1)
        assert state.tracking == "applied" and state.notes == "Dilekçe hazır"
        assert db.scalar(select(UserVerification)).decision == "eligible"
        assert build_matches(db, full=False)["jobs"][0]["tracking"] == "applied"


# ---------------------------------------------------------------------------
# Tarih çıkarımı, olaylar ve görevler
# ---------------------------------------------------------------------------

NOTICE = """Başvurular 01.12.2026 - 15.12.2026 tarihleri arasında saat 17:00'ye kadar yapılacaktır.
Yazılı sınav 22 Aralık 2026 tarihinde Ankara'da yapılacaktır.
Sınav sonuçları 28.12.2026 tarihinde www.ornek.gov.tr adresinde ilan edilecektir.
16.12.2017 tarihli ve 30272 sayılı Resmî Gazete'de yayımlanan yönetmelik uyarınca alım yapılacaktır.
01.01.1991 tarihinde veya bu tarihten sonra doğmuş olmak.
Sözlü sınav tarihi daha sonra duyurulacaktır."""


def test_dates_are_extracted_with_evidence_and_never_invented():
    events = extract_events(NOTICE, today=date(2026, 11, 16))
    assert [(event["kind"], event["date"]) for event in events] == [("exam", date(2026, 12, 22)), ("result", date(2026, 12, 28))]
    assert events[1]["url"] == "https://www.ornek.gov.tr" and "ilan edilecektir" in events[1]["evidence"]
    assert events[0]["time"] == ""  # saat yazmıyorsa tüm gün
    # Tarihi olmayan sözlü sınav, mevzuat ve doğum tarihi olay üretmez.
    assert extract_events("Sınav tarihi daha sonra duyurulacaktır. Sonuçlar internet sitesinde ilan edilecektir.") == []
    assert extract_events("") == []


def test_job_events_keep_user_edits_and_record_date_changes():
    with _database() as db:
        job = _job(description=NOTICE, application_start=date(2026, 12, 1), application_deadline=date(2026, 12, 15))
        db.add(job)
        db.commit()
        sync_job_events(db, job, today=date(2026, 11, 16))
        db.commit()
        kinds = {event.kind: event for event in db.scalars(select(JobEvent)).all()}
        assert set(kinds) == {"application_start", "application_deadline", "exam", "result"}
        assert kinds["application_deadline"].event_time == "17:00" and "saat 17:00" in kinds["application_deadline"].evidence
        assert sync_job_events(db, job, today=date(2026, 11, 16)) == {"created": 0, "changed": 0}  # çift olay oluşmaz

        kinds["exam"].event_date, kinds["exam"].user_edited = date(2026, 12, 23), True  # kullanıcı düzeltti
        job.application_deadline = date(2026, 12, 20)  # resmî kaynakta tarih değişti
        job.description = NOTICE.replace("15.12.2026", "20.12.2026")
        db.commit()
        assert sync_job_events(db, job, today=date(2026, 11, 16))["changed"] == 1
        db.commit()
        deadline = db.scalar(select(JobEvent).where(JobEvent.kind == "application_deadline"))
        assert deadline.event_date == date(2026, 12, 20) and deadline.previous_date == date(2026, 12, 15)
        assert db.scalar(select(JobEvent).where(JobEvent.kind == "exam")).event_date == date(2026, 12, 23)  # ezilmedi


def test_recurring_tasks_and_daily_notifications():
    today = date(2026, 12, 14)  # Pazartesi
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="Bilgisayar Mühendisliği", kpss_scores='{"P3": 87}'))
        db.add(_job(application_start=today - timedelta(days=3), application_deadline=today))
        daily = UserTask(title="İngilizce çalış", task_date=today - timedelta(days=5), recurrence="daily", created_at=datetime.now())
        mondays = UserTask(title="KPSS çalış", task_date=today - timedelta(days=14), recurrence="weekdays", weekdays="0", created_at=datetime.now())
        db.add_all([daily, mondays])
        db.commit()
        sync_job_events(db, db.get(Job, 1), today=today)
        db.commit()
        assert task_occurs_on(mondays, today) and not task_occurs_on(mondays, today + timedelta(days=1))

        assert notifications.refresh_daily(db, today=today) == 2
        titles = [item.title for item in db.scalars(select(Notification)).all()]
        assert any(title.startswith("Bugün son gün") for title in titles) and any("Bugünkü görevlerin (2)" in title for title in titles)
        assert notifications.refresh_daily(db, today=today) == 0  # aynı gün ikinci kez oluşmaz

        # "Başvurdum" işaretlenince son gün hatırlatması kapanır; elle "uygun değil" de kapatır.
        main.update_tracking(1, TrackingUpdate(tracking="applied"), db=db)
        assert notifications.refresh_daily(db, today=today + timedelta(days=0)) == 0
        db.query(Notification).delete()
        db.commit()
        assert not any(n.kind == "deadline" for n in db.scalars(select(Notification)).all())
        notifications.refresh_daily(db, today=today)
        assert not any(n.kind == "deadline" for n in db.scalars(select(Notification)).all())


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def _scanned_pdf() -> bytes:
    """Metin katmanı olmayan, yalnızca görüntü içeren bir PDF üretir."""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1240, 420), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    for index, line in enumerate((
        "ORNEK BELEDIYE BASKANLIGI MEMUR ALIM ILANI",
        "Herhangi bir lisans programindan mezun olmak.",
        "KPSS P3 puan turunden en az 70 puan almis olmak.",
        "Basvurular 01.12.2026 - 15.12.2026 tarihleri arasinda yapilacaktir.",
    )):
        draw.text((40, 40 + index * 80), line, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


def test_scanned_pdf_is_read_with_ocr_and_stays_for_manual_review(monkeypatch):
    pytest.importorskip("rapidocr_onnxruntime")
    from backend.sources.base import BaseJobSource

    monkeypatch.setenv("CAREERPILOT_OCR", "on")
    detail = BaseJobSource.document_detail("https://kamuilan.sbb.gov.tr/ilan.pdf", _scanned_pdf(), "application/pdf")
    parsed = detail["document"]["parsed"]
    assert parsed["ocr_confidence"] is not None and 0 < parsed["ocr_confidence"] <= 1
    assert "kpss" in detail["source_text"].casefold() and "lisans" in detail["source_text"].casefold()

    # OCR ile okunan ilan otomatik "Uygun" olmaz; şartlar gösterilir ama elle doğrulama beklenir.
    result = classify_public_job({"title": "Memur Alımı", "description": detail["source_text"], "ocr": True}, _engineer())
    assert result["category"] == POTANSIYEL
    assert any(item["name"] == "Belge okuma" and item["status"] == "unknown" for item in result["requirements"])


def test_application_keeps_working_when_ocr_is_off_or_fails(monkeypatch):
    from backend.documents import ScannedDocumentError
    from backend.sources.base import BaseJobSource

    monkeypatch.setenv("CAREERPILOT_OCR", "off")
    with pytest.raises(ScannedDocumentError, match="Taranmış PDF okunamadı"):
        BaseJobSource.document_detail("https://kamuilan.sbb.gov.tr/ilan.pdf", _scanned_pdf(), "application/pdf")

    class Source:
        source_name = "SBB Kamu İlanları"
        pages_checked = 1
        calls = 0

        def fetch_listings(self):
            return [{"detail_url": "https://kamuilan.sbb.gov.tr/ilanDetay.aspx?kod=1", "external_id": "a", "user_url": "https://kamuilan.sbb.gov.tr/",
                     "title": "1 Memur Alacak", "institution": "Örnek Belediye Başkanlığı", "content_hash": "v1",
                     "application_start_date": date.today(), "application_end_date": date.today() + timedelta(days=9)}]

        def fetch_detail(self, url):
            Source.calls += 1
            return BaseJobSource.document_detail(url, _scanned_pdf(), "application/pdf")

    monkeypatch.setattr(main, "get_source_registry", lambda: {"sbb": Source()})
    with _database() as db:
        first = main.sync_all_sources(db)
        second = main.sync_all_sources(db)
        assert first["results"]["sbb"]["detail_failed"] == 1 and Source.calls == 1  # her taramada yeniden denenmez
        assert second["results"]["sbb"]["status"] in ("ok", "partial")
        item = build_matches(db, full=False)["jobs"][0]
        assert item["category"] == POTANSIYEL and item["data_status"] == "listing_only"  # ilan kaybolmaz, tahmin yürütülmez
        # Okunamayan PDF'ten tarih uydurulmaz; yalnızca kaynağın listesindeki başvuru tarihleri vardır.
        assert {event.kind for event in db.scalars(select(JobEvent)).all()} == {"application_start", "application_deadline"}
        failed = main.list_sources(db)[0]["failed_items"]
        assert failed[0]["scanned"] is True and "Taranmış PDF okunamadı" in failed[0]["reason"]
