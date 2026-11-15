"""Motorun belirli bir bölüme bağlı olmadığını ve yeni özellikleri doğrulayan testler."""

from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import main, notifications
from backend.database import Base
from backend.documents import _generic_table_positions
from backend.eligibility import build_candidate_profile, classify_public_job
from backend.matching import build_matches
from backend.models import CandidateProfile, Job, Notification
from backend.schemas import NotificationSettings, ProfileUpdate, TrackingUpdate
from backend.sync import _mark_cancelled, application_window_from_text, organization_key

UYGUN, POTANSIYEL, DEGIL = "UYGUN", "POTANSİYEL OLARAK UYGUN", "UYGUN DEĞİL"


def candidate(**overrides):
    data = {"degree": "Lisans", "department": "İktisat", "faculty": "İktisadi ve İdari Bilimler Fakültesi",
            "kpss_scores": {"P3": 82.0, "P48": 85.0}, "age": 27}
    data.update(overrides)
    return build_candidate_profile(data)


def test_department_match_is_not_tied_to_computer_engineering():
    job = {"title": "Uzman Yardımcısı", "description": (
        "En az dört yıllık lisans eğitimi veren Hukuk, İktisat, İşletme bölümlerinden mezun olmak.\n"
        "KPSSP48 puan türünden 80 (seksen) ve üzerinde puan almış olmak."
    )}
    result = classify_public_job(job, candidate())
    assert result["category"] == UYGUN
    assert result["kpss"]["score_types"] == ["P48"] and result["kpss"]["minimum_score"] == 80
    assert result["kpss"]["candidate_score_type"] == "P48"

    engineer = candidate(department="Makine Mühendisliği", faculty="Mühendislik Fakültesi")
    assert classify_public_job(job, engineer)["category"] == DEGIL


def test_faculty_level_acceptance_and_shared_type_word_lists():
    by_faculty = {"title": "Stajyer Kontrolör", "description": (
        "Hukuk, Siyasal Bilgiler, İktisadi ve İdari Bilimler Fakültelerinden mezun olması."
    )}
    assert classify_public_job(by_faculty, candidate(department="Maliye"))["education"]["status"] == "met"

    shared = {"title": "Mühendis", "description": "Bilgisayar, Yazılım ve Elektronik Mühendisliği bölümlerinden mezun olmak."}
    electronics = candidate(department="Elektronik Mühendisliği", faculty="")
    assert classify_public_job(shared, electronics)["education"]["status"] == "met"


def test_department_alias_counts_as_match():
    job = {"title": "Programcı", "description": "Yazılım Mühendisliği bölümünden mezun olmak."}
    base = candidate(department="Bilgisayar Mühendisliği", faculty="")
    assert classify_public_job(job, base)["education"]["status"] == "unknown"
    with_alias = candidate(department="Bilgisayar Mühendisliği", faculty="", department_aliases="Yazılım Mühendisliği")
    assert classify_public_job(job, with_alias)["education"]["status"] == "met"


def test_degree_level_and_any_program_codes():
    associate = candidate(degree="Ön Lisans", department="Bilgisayar Programcılığı", faculty="", kpss_scores={"P93": 88})
    bachelor_only = {"title": "Memur", "qualification_codes": "4001", "kpss_score_type": "P3"}
    assert classify_public_job(bachelor_only, associate)["category"] == DEGIL
    any_associate = {"title": "Memur", "qualification_codes": "3001", "kpss_score_type": "P93", "kpss_min_score": 70}
    assert classify_public_job(any_associate, associate)["category"] == UYGUN
    # Lisans mezunu, ön lisans düzeyindeki kadroya o düzeyin puanı olmadan yerleşemez.
    assert classify_public_job(any_associate, candidate())["category"] == DEGIL


def test_missing_score_type_is_reported_with_registered_types():
    job = {"title": "Uzman", "description": "İktisat bölümünden mezun olmak. KPSS P17 puan türünden en az 75 puan almış olmak."}
    result = classify_public_job(job, candidate())
    assert result["category"] == DEGIL
    assert "P17" in result["reason"] and "P3" in result["reason"]


def test_academic_special_group_and_gender_rows():
    academic = classify_public_job({"title": "12 ÖĞRETİM ELEMANI ALACAK", "description": ""}, candidate())
    assert academic["category"] == DEGIL and academic["kind"] == "academic"

    special = {"title": "ESKİ HÜKÜMLÜ İŞÇİ ALIM İLANI", "description": "En az ilkokul mezunu olmak."}
    assert classify_public_job(special, candidate())["category"] == DEGIL
    assert classify_public_job(special, candidate(special_status="eski hükümlü"))["category"] != DEGIL

    row = {"title": "Zabıta Memuru", "position": "Zabıta Memuru", "position_specific": True, "kpss_score_type": "P3",
           "education_requirement": "Herhangi bir lisans programından mezun olmak.",
           "description": "Herhangi bir lisans programından mezun olmak. Cinsiyet: Erkek."}
    assert classify_public_job(row, candidate(gender="Kadın"))["category"] == DEGIL
    assert classify_public_job(row, candidate(gender="Erkek"))["category"] == UYGUN
    assert classify_public_job(row, candidate())["category"] == POTANSIYEL


def test_title_profession_is_used_when_text_is_missing():
    result = classify_public_job({"title": "1 SÖZLEŞMELİ PSİKOLOG ALACAK", "description": ""}, candidate())
    assert result["category"] == DEGIL and "Psikolog" in result["reason"]
    assert result["data_quality"] == "listing_only"


def test_pdf_line_wraps_do_not_hide_requirements():
    text = (
        "c) Ölçme, Seçme ve Yerleştirme Merkezi Başkanlığı (ÖSYM) tarafından 2025 ve\n"
        "2026 yıllarında yapılan Kamu Personel Seçme Sınavlarının KPSSP17, KPSSP18,\n"
        "KPSSP22 puan türlerinin herhangi birinden 80 (seksen) ve üzerinde puan almış olması,\n"
        "d) Giriş sınavının yapıldığı yılın Ocak ayının birinci günü itibarıyla 35 (otuz beş) yaşını\n"
        "doldurmamış olması,"
    )
    result = classify_public_job({"title": "Uzman", "description": text}, candidate(age=36, kpss_scores={"P18": 90}))
    assert result["kpss"]["score_types"] == ["P17", "P18", "P22"]
    assert result["kpss"]["minimum_score"] == 80 and result["kpss"]["status"] == "met"
    assert any(item["name"] == "Yaş" and item["status"] == "not_met" for item in result["requirements"])


def test_generic_staff_table_rows_and_continuation_pages():
    header = ["Sıra No", "Kadro Ünvanı", "Hizmet Sınıfı", "Kadro Derecesi", "Kadro Adedi", "Niteliği", "Cinsiyeti", "KPSS Puan Türü", "KPSS Taban Puanı"]
    rows, mapping = _generic_table_positions([
        header,
        ["1", "Mühendis", "TH", "5", "1", "Makine mühendisliği programından mezun olmak.", "Erkek/ Kadın", "P3", "En az 70 Puan"],
        ["2", "Zabıta Memuru", "GİH", "10", "3", "Herhangi bir ön lisans programından mezun olmak.", "Erkek", "P93", "60"],
        ["", "", "", "", "TOPLAM", "", "", "", ""],
    ])
    assert [row["position_title"] for row in rows] == ["Mühendis", "Zabıta Memuru"]
    assert rows[0]["quota"] == "1" and rows[0]["kpss_score_type"] == "P3" and rows[0]["kpss_min_score"] == 70
    assert "Cinsiyet" not in rows[0]["requirements_text"]
    assert rows[1]["requirements_text"].endswith("Cinsiyet: Erkek.")

    continued, _ = _generic_table_positions(
        [["3", "Tekniker", "TH", "9", "2", "İnşaat teknolojisi programından mezun olmak.", "Kadın", "P93", "65"]],
        mapping, len(rows),
    )
    assert continued[0]["position_title"] == "Tekniker" and continued[0]["row_index"] == 3


def test_application_window_and_organization_keys():
    start, end = application_window_from_text("Başvurular, 23.11.2026 - 04.12.2026 tarihleri arasında e-Devlet üzerinden yapılacaktır.")
    assert (start, end) == (date(2026, 11, 23), date(2026, 12, 4))
    assert organization_key("Edirne Keşan Belediyesi") == organization_key("Keşan Belediye Başkanlığı")
    assert organization_key("TÜRKİYE ŞEKER FABRİKALARI A.Ş. GENEL MÜDÜRLÜĞÜ") == organization_key("Türkiye Şeker Fabrikaları A.Ş.")
    assert organization_key("Ankara Üniversitesi") != organization_key("Ankara Sosyal Bilimler Üniversitesi")


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _job(**overrides):
    data = dict(
        sector="public", title="5 Uzman Yardımcısı Alacak", organization="Örnek Kurumu", source_name="SBB Kamu İlanları",
        source_url="https://kamuilan.sbb.gov.tr/", application_start=date.today() - timedelta(days=2),
        application_deadline=date.today() + timedelta(days=2),
        description="İktisat, İşletme bölümlerinden mezun olmak. KPSS P48 puan türünden en az 80 puan almış olmak. " * 3,
    )
    data.update(overrides)
    return Job(**data)


def test_profile_api_stores_multiple_kpss_scores_without_default_personal_data():
    with _database() as db:
        empty = main.get_profile(db)
        assert empty.department == "" and empty.kpss_scores == {}
        saved = main.update_profile(ProfileUpdate(
            degree="Lisans", department="İktisat", faculty="İktisadi ve İdari Bilimler Fakültesi",
            kpss_scores={"p3": 81.5, "KPSSP48": 86.25}, gender="Kadın",
        ), db=db)
        assert saved.kpss_scores == {"P3": 81.5, "P48": 86.25}
        assert saved.kpss_score_type == "P3" and saved.kpss_p3 == 81.5
        legacy = main.update_profile(ProfileUpdate(department="İktisat", kpss_score_type="P3", kpss_p3=70), db=db)
        assert legacy.kpss_scores == {"P3": 70.0}


def test_duplicates_across_sources_are_merged_and_tracking_is_saved():
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="İktisat", kpss_scores='{"P48": 85}'))
        db.add(_job())
        db.add(_job(source_name="İŞKUR Kamu Memur Alım İlanları", organization="Örnek Kurumu Başkanlığı",
                    title="Örnek Kurumu Uzman Yardımcısı Alım İlanı", description="kısa",
                    source_url="https://www.iskur.gov.tr/medya/x.pdf"))
        db.add(_job(title="3 Memur Alacak", description="Hukuk bölümünden mezun olmak. " * 5))  # aynı kaynaktan ayrı ilan
        db.commit()

        result = build_matches(db, full=False)
        assert result["counts"]["total"] == 2
        primary = next(item for item in result["jobs"] if item["match"]["category"] == UYGUN)
        assert primary["also_listed"][0]["source_name"].startswith("İŞKUR")
        assert primary["days_left"] == 2 and "description" not in primary

        main.update_tracking(primary["parent_job_id"], TrackingUpdate(tracking="saved", notes="Belgeleri hazırla"), db=db)
        detail = main.job_detail(primary["parent_job_id"], db=db)
        assert detail["tracking"] == "saved" and detail["notes"] == "Belgeleri hazırla"
        assert detail["positions"][0]["match"]["category"] == UYGUN and len(detail["description"]) > 100


def test_notifications_are_created_once_and_respect_preferences(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="İktisat", kpss_scores='{"P48": 85}'))
        db.add(_job())
        db.add(_job(title="2 Memur Alacak", organization="Başka Kurum", description="Hukuk bölümünden mezun olmak. " * 5))
        db.add(_job(title="1 Uzman Alacak", organization="Eski Kurum", application_deadline=date.today() - timedelta(days=1)))
        db.commit()
        notifications.save_settings(db, NotificationSettings(email_enabled=True, email_to="aday@example.com", deadline_reminder_days=3))

        first = notifications.process_notifications(db)
        second = notifications.process_notifications(db)
        items = list(db.scalars(select(Notification).order_by(Notification.id)).all())

        assert first["created"] == 2 and second["created"] == 0
        assert {item.kind for item in items} == {"new_match", "deadline"}
        assert all(item.delivered_at is not None for item in items)
        assert len(sent) == 1 and sent[0][0] == "aday@example.com"
        assert "1 yeni uygun ilan" in sent[0][1] and "Örnek Kurumu" in sent[0][2]

        listing = main.list_notifications(unread_only=False, limit=50, db=db)
        assert listing["unread"] == 2
        main.read_notification(listing["items"][0]["id"], db=db)
        assert main.list_notifications(unread_only=True, limit=50, db=db)["unread"] == 1
        assert main.read_all_notifications(db=db) == {"unread": 0}


def test_failed_channel_is_retried_and_hidden_jobs_are_skipped(monkeypatch):
    def broken(*_args):
        raise RuntimeError("SMTP kapalı")

    monkeypatch.setattr(notifications, "send_email", broken)
    with _database() as db:
        db.add(CandidateProfile(id=1, degree="Lisans", department="İktisat", kpss_scores='{"P48": 85}'))
        db.add(_job(application_deadline=date.today() + timedelta(days=20)))
        db.add(_job(organization="Gizlenen Kurum", tracking="hidden", application_deadline=date.today() + timedelta(days=20)))
        db.commit()
        notifications.save_settings(db, NotificationSettings(email_enabled=True, email_to="aday@example.com"))

        result = notifications.process_notifications(db)
        assert result["created"] == 1 and result["channels"]["email"].startswith("hata")
        assert db.scalar(select(Notification)).delivered_at is None  # sonraki taramada yeniden denenir


def test_cancellation_marks_matching_listing_in_every_source():
    with _database() as db:
        db.add(_job(organization="Asarcık Belediye Başkanlığı", title="9 MEMUR ALACAK"))
        db.add(_job(organization="Asarcık Belediye Başkanlığı", title="2 İTFAİYE ERİ ALACAK"))
        db.commit()
        count = _mark_cancelled(db, "Yerel Yönetimler Genel Müdürlüğü", {
            "institution": "Asarcık Belediyesi", "title": "SAMSUN İLİ ASARCIK BELEDİYESİ MEMUR ALIMI İPTAL İLANI",
        })
        db.commit()
        statuses = {job.title: job.status for job in db.scalars(select(Job)).all()}
        assert count == 1
        assert statuses["9 MEMUR ALACAK"] == "İptal edildi" and statuses["2 İTFAİYE ERİ ALACAK"] != "İptal edildi"
        cancelled = next(item for item in build_matches(db, full=False)["jobs"] if item["title"] == "9 MEMUR ALACAK")
        assert cancelled["application_status"] == "İptal Edildi" and cancelled["is_expired"] is True
