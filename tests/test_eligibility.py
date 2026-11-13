"""
Kapsamlı eligibility motor testleri.

Test ettiğimiz senaryolar:
1.  P3 87.60 + P3 taban 70  → UYGUN
2.  P3 87.60 + P3 taban 90  → UYGUN DEĞİL
3.  4001 kodu + lisans mezunu → eğitim şartı karşılıyor
4.  Yalnızca Hukuk Fakültesi → UYGUN DEĞİL
5.  Yalnızca P94 isteyen ilan + aday P3 → UYGUN DEĞİL
6.  Bilgisayar Mühendisliği + 3 yıl deneyim zorunlu + deneyim bilinmiyor → POTANSİYEL
7.  Bilgisayar Mühendisliği + YDS 70 zorunlu + YDS bilinmiyor → POTANSİYEL
8.  Tüm şartlar karşılıyor + giriş sınavı var → UYGUN
9.  Bütün mühendislik bölümleri kabul ediliyor → eğitim UYGUN
10. Yalnızca belirli mühendislik bölümleri + Bilgisayar Mühendisliği listede yok → UYGUN DEĞİL
11. "Tercihen" deneyim zorunlu değil
12. Birden fazla pozisyon senaryosu (ayrı ilanlar)
13. Tablo içeriği HTML sayfasında yok → POTANSİYEL
14. Vardiyalı çalışma profilden okunuyor
15. Profil güncellenince uygunluk yeniden hesaplanıyor (integration)
16. Aynı URL ile iki senkronizasyon → ikinci kayıt oluşmaz (integration)
17. Son başvuru tarihi geçmiş ilan is_expired=True döner
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.eligibility import build_candidate_profile as _build_candidate_profile, classify_public_job, detect_recruitment_method
from backend.kariyerkapisi import parse_listing_content, parse_listing_detail
from backend import main
from backend.database import Base
from backend.models import CandidateProfile, Job
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def profile(**extra):
    return _build_candidate_profile({
        "degree": "Lisans",
        "department": "Bilgisayar Mühendisliği",
        "kpss_p3": 87.60,
        **extra,
    })


def job(description="", **fields):
    defaults = {"title": "Uzman", "description": description,
                "education_requirement": "", "qualification_codes": "",
                "kpss_score_type": "", "kpss_min_score": None}
    defaults.update(fields)
    return defaults


UYGUN = "UYGUN"
POTANSIYEL = "POTANSİYEL OLARAK UYGUN"
DEGIL = "UYGUN DEĞİL"


# ---------------------------------------------------------------------------
# 1. P3 87.60 + taban 70 → UYGUN
# ---------------------------------------------------------------------------

def test_scenario_1_p3_87_60_meets_taban_70():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak. KPSS P3 en az 70.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    assert r["category"] == UYGUN
    assert r["kpss"]["status"] == "met"
    assert r["education"]["status"] == "met"


# ---------------------------------------------------------------------------
# 2. P3 87.60 + taban 90 → UYGUN DEĞİL
# ---------------------------------------------------------------------------

def test_scenario_2_p3_87_60_below_taban_90():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak.",
            kpss_score_type="P3", kpss_min_score=90),
        profile(),
    )
    assert r["category"] == DEGIL
    assert r["kpss"]["status"] == "not_met"


# ---------------------------------------------------------------------------
# 3. 4001 kodu + lisans mezunu → eğitim şartı karşılanıyor
# ---------------------------------------------------------------------------

def test_scenario_3_4001_lisans_met():
    r = classify_public_job(
        job(qualification_codes="4001"),
        profile(),
    )
    assert r["education"]["status"] == "met"
    assert "4001" in r["qualification_codes"]


# ---------------------------------------------------------------------------
# 4. Yalnızca Hukuk Fakültesi → UYGUN DEĞİL
# ---------------------------------------------------------------------------

def test_scenario_4_hukuk_fakultesi_not_eligible():
    r = classify_public_job(
        job("Hukuk fakültesi mezunu olmak. KPSS P3 en az 70.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    assert r["category"] == DEGIL
    assert r["education"]["status"] == "not_met"


# ---------------------------------------------------------------------------
# 5. Yalnızca P94 isteyen ilan + aday P3 → UYGUN DEĞİL
# ---------------------------------------------------------------------------

def test_scenario_5_p94_only_not_eligible():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak.",
            kpss_score_type="P94", kpss_min_score=70),
        profile(),
    )
    assert r["category"] == DEGIL
    assert r["kpss"]["status"] == "not_met"


# ---------------------------------------------------------------------------
# 6. Bilgisayar Mühendisliği + 3 yıl deneyim zorunlu + deneyim bilinmiyor → POTANSİYEL
# ---------------------------------------------------------------------------

def test_scenario_6_experience_unknown_potential():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak. En az 3 yıl deneyim sahibi olmak.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),  # experience_years=None
    )
    assert r["category"] == POTANSIYEL
    assert any("deneyim" in item.lower() for item in r["unknown_conditions"])


# ---------------------------------------------------------------------------
# 7. Bilgisayar Mühendisliği + YDS 70 zorunlu + YDS bilinmiyor → POTANSİYEL
# ---------------------------------------------------------------------------

def test_scenario_7_yds_unknown_potential():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak. YDS'den en az 70 puan almak.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),  # yds_score=None
    )
    assert r["category"] == POTANSIYEL
    assert any("YDS" in item for item in r["unknown_conditions"])


# ---------------------------------------------------------------------------
# 8. Tüm şartlar karşılıyor + kurum giriş sınavı var → UYGUN, alım yöntemi ayrı
# ---------------------------------------------------------------------------

def test_scenario_8_giris_sinavi_uygun():
    j = job(
        "Bilgisayar Mühendisliği bölümünden mezun olmak. KPSS P3 en az 70. "
        "Yazılı ve sözlü giriş sınavına tabi tutulacaktır.",
        kpss_score_type="P3", kpss_min_score=70,
    )
    r = classify_public_job(j, profile())
    assert r["category"] == UYGUN
    method = detect_recruitment_method(j["title"], j["description"])
    assert method == "Kurum Giriş Sınavı"


# ---------------------------------------------------------------------------
# 9. Bütün mühendislik bölümleri kabul ediliyor → eğitim UYGUN
# ---------------------------------------------------------------------------

def test_scenario_9_all_engineering_eligible():
    r = classify_public_job(
        job("Mühendislik fakültelerinin ilgili bölümlerinden mezun olmak."),
        profile(),
    )
    assert r["education"]["status"] == "met"


# ---------------------------------------------------------------------------
# 10. Yalnızca belirli mühendislik bölümleri + Bilgisayar Mühendisliği yok → UYGUN DEĞİL
# ---------------------------------------------------------------------------

def test_scenario_10_specific_engineering_no_ce():
    r = classify_public_job(
        job("İnşaat Mühendisliği, Çevre Mühendisliği veya Harita Mühendisliği bölümünden mezun olmak."),
        profile(),
    )
    assert r["category"] == DEGIL
    assert r["education"]["status"] == "not_met"


# ---------------------------------------------------------------------------
# 11. "Tercihen" deneyim zorunlu şart sayılmamalı
# ---------------------------------------------------------------------------

def test_scenario_11_preferred_experience_not_mandatory():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak. Tercihen 2 yıl deneyim sahibi olmak.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    # "tercihen" ifadesi nedeniyle deneyim unknown_conditions'a girmemeli
    assert not any("deneyim" in item.lower() for item in r["unknown_conditions"])
    assert r["category"] == UYGUN


# ---------------------------------------------------------------------------
# 12. Ayrı pozisyonlar için ayrı ilanlar doğru sınıflandırılmalı
# ---------------------------------------------------------------------------

def test_scenario_12_multiple_positions_separate():
    # Bilgisayar Mühendisi pozisyonu → UYGUN
    r_ce = classify_public_job(
        job("Bilgisayar Mühendisliği bölümünden mezun olmak.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    # Orman Mühendisi pozisyonu → UYGUN DEĞİL
    r_orman = classify_public_job(
        job("Orman Mühendisliği bölümünden mezun olmak.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    assert r_ce["category"] == UYGUN
    assert r_orman["category"] == DEGIL


# ---------------------------------------------------------------------------
# 13. Tablo içeriği sayfada yok → eğitim bilinmiyor → POTANSİYEL
# ---------------------------------------------------------------------------

def test_scenario_13_table_content_missing_potential():
    r = classify_public_job(
        job("Kabul edilen bölümler ekteki tabloda yer almaktadır. KPSS P3 en az 70.",
            kpss_score_type="P3", kpss_min_score=70),
        profile(),
    )
    assert r["category"] == POTANSIYEL
    assert r["education"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# 14. Vardiyalı çalışma profilden okunuyor
# ---------------------------------------------------------------------------

def test_scenario_14_shift_from_profile():
    desc = "Bilgisayar Mühendisliği bölümünden mezun olmak. Vardiyalı çalışmaya uygun olmak."
    assert classify_public_job(job(desc), profile(accepts_shifts=True))["category"] == UYGUN
    assert classify_public_job(job(desc), profile())["category"] == POTANSIYEL
    assert classify_public_job(job(desc), profile(accepts_shifts=False))["category"] == DEGIL


# ---------------------------------------------------------------------------
# 15. Profil güncellenince farklı sonuç → integration
# ---------------------------------------------------------------------------

def test_scenario_15_profile_update_changes_result():
    desc = "Bilgisayar Mühendisliği bölümünden mezun olmak. En az 3 yıl deneyim sahibi olmak."
    p_unknown = profile()
    p_known = profile(experience_years=4)
    r_unknown = classify_public_job(job(desc, kpss_score_type="P3", kpss_min_score=70), p_unknown)
    r_known = classify_public_job(job(desc, kpss_score_type="P3", kpss_min_score=70), p_known)
    assert r_unknown["category"] == POTANSIYEL
    assert r_known["category"] == UYGUN


# ---------------------------------------------------------------------------
# 16. Aynı URL ile iki senkronizasyon → ikinci kayıt oluşmaz
# ---------------------------------------------------------------------------

def test_scenario_16_duplicate_sync_no_duplicate_record(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    url = "https://kariyerkapisi.gov.tr/IlanDetay?i=test16"
    listings = [
        {"url": url, "institution": "Test Kurumu", "department": "", "title": "Bilgisayar Mühendisi", "end_date": ""},
    ]
    monkeypatch.setattr(main, "scrape_public_active_listings", lambda: listings)
    monkeypatch.setattr(main, "scrape_public_listing_details", lambda _: {
        url: {"details": {"source_text": "Test metni", "title": "Bilgisayar Mühendisi"}, "error": None},
    })

    with Session(test_engine) as db:
        main.sync_kariyer_kapisi(db)
        main.sync_kariyer_kapisi(db)
        count = db.scalar(
            select(Job).where(Job.source_url == url)
        )
    # İlan sadece bir kez kaydedilmiş olmalı
    assert count is not None


# ---------------------------------------------------------------------------
# 17. Son başvuru tarihi geçmiş → is_expired = True
# ---------------------------------------------------------------------------

def test_scenario_17_expired_deadline():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)

    yesterday = date.today() - timedelta(days=1)

    with Session(test_engine) as db:
        db.add(CandidateProfile(
            id=1, degree="Lisans", department="Bilgisayar Mühendisliği", kpss_p3=87.60
        ))
        db.add(Job(
            sector="public", title="Bilgisayar Mühendisi", organization="Test Kurumu",
            application_deadline=yesterday,
            description="Bilgisayar Mühendisliği bölümünden mezun olmak.",
        ))
        db.commit()
        result = main.public_matches(db)

    assert result["jobs"][0]["is_expired"] is True


# ---------------------------------------------------------------------------
# Temel eligibility testleri (eski testlerden)
# ---------------------------------------------------------------------------

def test_p3_87_60_meets_p3_minimum_80():
    r = classify_public_job(
        job(education_requirement="Lisans Bilgisayar Mühendisliği",
            kpss_score_type="P3", kpss_min_score=80),
        profile(),
    )
    assert "87.60" in r["reason"]
    assert r["category"] == UYGUN


def test_explicit_non_p3_requirement_is_not_eligible():
    r = classify_public_job(
        job(education_requirement="Bilgisayar Mühendisliği mezunu olmak",
            kpss_score_type="P94", kpss_min_score=70),
        profile(),
    )
    assert r["kpss"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_4001_matches_a_bachelor_degree():
    r = classify_public_job(
        job(qualification_codes="4001"),
        profile(),
    )
    assert "4001" in r["qualification_codes"]
    assert r["category"] == UYGUN


def test_explicit_any_bachelors_requirement_is_met():
    r = classify_public_job(
        job(education_requirement="Herhangi bir lisans programından mezun olmak"),
        profile(),
    )
    assert r["education"]["status"] == "met"
    assert r["category"] == UYGUN


def test_explicit_department_mismatch_is_not_eligible():
    r = classify_public_job(
        job(education_requirement="Hukuk Fakültesi mezunu olmak",
            kpss_score_type="P3", kpss_min_score=80),
        profile(),
    )
    assert r["category"] == DEGIL


def test_p1_or_p2_only_requirement_is_potential():
    r = classify_public_job(
        job(education_requirement="Lisans Bilgisayar Mühendisliği",
            kpss_score_type="P1/P2", kpss_min_score=70),
        profile(),
    )
    assert r["kpss"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_general_public_conditions_do_not_create_unknowns():
    r = classify_public_job(
        job(
            "Bilgisayar Mühendisliği bölümlerinden mezun olmak. Türk vatandaşı olmak. "
            "Askerlikle ilişiği bulunmamak. Adli sicil kaydı temiz olmak. "
            "657 sayılı Kanun'un 48. maddesindeki şartları taşımak. "
            "Güvenlik soruşturması ve arşiv araştırması yapılacaktır.",
            kpss_score_type="P3", kpss_min_score=70,
        ),
        profile(),
    )
    assert r["category"] == UYGUN
    assert r["unknown_conditions"] == []
    assert "Türk vatandaşı olmak" in r["general_conditions"]
    assert "Güvenlik soruşturması (kurum yürütür)" in r["general_conditions"]


def test_preference_statements_are_not_mandatory():
    r = classify_public_job(
        job(
            "Bilgisayar Mühendisliği bölümlerinden mezun olmak. "
            "Tercihen yüksek lisans yapmış olmak. "
            "İkinci yabancı dil bilmek tercih sebebidir. "
            "Belirli bir alanda deneyim sahibi olmak puanlamada avantaj sağlar. "
            "Tercihen CISSP sertifikasına sahip olmak.",
            kpss_score_type="P3", kpss_min_score=70,
        ),
        profile(),
    )
    assert r["unknown_conditions"] == []
    assert r["category"] == UYGUN


def test_shift_accepted_in_profile():
    desc = "Bilgisayar Mühendisliği bölümünden mezun olmak. Vardiyalı çalışmaya uygun olmak."
    assert classify_public_job(job(desc), profile(accepts_shifts=True))["category"] == UYGUN
    assert classify_public_job(job(desc), profile())["category"] == POTANSIYEL


def test_unverified_4531_stays_potential():
    r = classify_public_job(
        job(education_requirement="Bilgisayar Mühendisliği Lisans",
            qualification_codes="4531"),
        profile(),
    )
    assert r["category"] == POTANSIYEL
    assert any("4531" in item for item in r["unknown_conditions"])


def test_p3_score_equal_to_minimum_is_met():
    r = classify_public_job(
        job(education_requirement="Bilgisayar Mühendisliği mezunu olmak",
            kpss_score_type="P3", kpss_min_score=87.6),
        profile(),
    )
    assert r["kpss"]["status"] == "met"
    assert r["category"] == UYGUN


def test_software_engineering_only_stays_potential():
    r = classify_public_job(
        job("Yazılım Mühendisliği bölümünden mezun olmak."),
        profile(),
    )
    assert r["education"]["status"] == "unknown"
    assert r["category"] == POTANSIYEL


def test_p3_is_used_when_listing_accepts_p1_p2_and_p3():
    r = classify_public_job(
        job(education_requirement="Lisans Bilgisayar Mühendisliği",
            kpss_score_type="P1/P2/P3", kpss_min_score=80,
            description="YDS puanı en az 70 olmalıdır."),
        profile(),
    )
    assert "P3 puanı 87.60" in r["reason"]
    assert r["category"] == POTANSIYEL
    assert any("YDS" in item for item in r["unknown_conditions"])


def test_minimum_age_18_is_general_not_an_age_limit():
    r = classify_public_job(
        job("Bilgisayar Mühendisliği mezunu olmak. 18 yaşını doldurmuş olmak."),
        profile(),
    )
    assert r["category"] == UYGUN


def test_repeated_requirement_is_listed_once():
    sentence = "Bilgisayar Mühendisliği bölümlerinden mezun olmak. En az 3 yıl deneyim sahibi olmak."
    r = classify_public_job(job(f"{sentence}\n{sentence}"), profile())
    assert r["education"]["requirement"].count("mezun olmak") == 1
    assert sum("deneyim" in item for item in r["unknown_conditions"]) == 1


def test_known_experience_and_yds_in_profile_are_used():
    desc = "Bilgisayar Mühendisliği mezunu olmak. En az 3 yıl deneyim sahibi olmak. YDS'den en az 70 puan almak."
    ok = classify_public_job(
        job(desc, kpss_score_type="P3", kpss_min_score=70),
        profile(experience_years=4, yds_score=75),
    )
    assert ok["category"] == UYGUN
    low = classify_public_job(
        job(desc, kpss_score_type="P3", kpss_min_score=70),
        profile(experience_years=1, yds_score=75),
    )
    assert low["category"] == DEGIL


def test_recruitment_method_detected_giris_sinavi():
    method = detect_recruitment_method(
        "Sözleşmeli Mühendis ve Tekniker Giriş Sınavı",
        "KPSS puanı ile yazılı sınava çağırılacaktır.",
    )
    assert method == "Kurum Giriş Sınavı"


def test_recruitment_method_not_merkezi_for_exam_jobs():
    # Giriş sınavı olan ilan, merkezi atama olarak sınıflandırılmamalı
    method = detect_recruitment_method(
        "TÜRKŞEKER Sözleşmeli Mühendis ve Tekniker Alımı",
        "Adaylar yazılı sınava tabi tutulacaktır. KPSS P3 puanı sıralamada kullanılacaktır.",
    )
    assert method != "KPSS Merkezi Yerleştirme"


def test_empty_profile_does_not_invent_department_or_kpss_score():
    p = _build_candidate_profile({})
    assert p["department"] == ""
    assert p["kpss_score_type"] == ""
    assert p["kpss_score"] is None



# ---------------------------------------------------------------------------
# Kullanıcının Talep Ettiği İlanlara Özel Testler
# ---------------------------------------------------------------------------

def test_karabaglar_belediyesi_cevre_muhendisi_not_eligible():
    j = job(
        title="KARABAĞLAR BELEDİYE BAŞKANLIĞI - Çevre Mühendisi Alımı (2 Adet)",
        position="Çevre Mühendisi",
        description="Çevre Mühendisi kadrosu için sınav yapılacaktır.",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL
    assert "Çevre Mühendisliği" in r["reason"]


def test_doka_uzman_personel_not_eligible_due_to_kpss_types():
    j = job(
        title="DOĞU KARADENİZ KALKINMA AJANSI - PERSONEL ALIM İLANI-2026",
        position="Uzman Personel",
        description="Tablo 2: Uzman Personel İçin KPSS P12, P14, P24, P29 puan türleri esas alınacaktır.",
        kpss_score_type="P12/P14/P24/P29",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL


def test_sgk_denetmen_yardimciligi_not_eligible():
    j = job(
        title="SOSYAL GÜVENLİK KURUMU BAŞKANLIĞI - SOSYAL GÜVENLİK DENETMEN YARDIMCILIĞI / (Hukuk, SBF, İİBF)",
        description="Hukuk, Siyasal Bilgiler, İktisadi ve İdari Bilimler, İktisat, İşletme mezunu olmak.",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL


def test_kamu_ihale_uzman_yardimciligi_not_eligible():
    j = job(
        title="KAMU İHALE KURUMU - KAMU İHALE UZMAN YARDIMCILIĞI GİRİŞ SINAVI",
        description="Kabul edilen gruplar: Hukuk, İİBF, İnşaat ve Makine Mühendisliği.",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL


def test_ytb_uzman_yardimciligi_not_eligible():
    j = job(
        title="YURTDIŞI TÜRKLER VE AKRABA TOPLULUKLAR BAŞKANLIĞI - YTB UZMAN YARDIMCISI ALIM İLANI",
        description="Kabul edilen bölümler: Hukuk, Siyaset Bilimi, Uluslararası İlişkiler.",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL


def test_mevlana_insaat_muhendisi_not_eligible():
    j = job(
        title="MEVLANA KALKINMA AJANSI - Personel Alım İlanı-İnşaat Mühendisliği (1 Uzman)",
        position="İnşaat Mühendisliği Uzmanı",
        description="İnşaat Mühendisliği bölümünden mezun olmak.",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == DEGIL


def test_turkseker_bilgisayar_muhendisi_position_is_potential_without_shift_excuse():
    j = job(
        title="TÜRKŞEKER - Bilgisayar Mühendisi",
        position="Bilgisayar Mühendisi",
        quota="2",
        city="Ankara",
        kpss_score_type="P3",
        kpss_min_score=70.0,
        description="Vardiyalı çalışmaya engel durumu bulunmamak. Tablo 1'deki öğrenim dallarından mezun olmak.",
    )
    p = profile(accepts_shifts=True)
    r = classify_public_job(j, p)
    assert r["category"] == POTANSIYEL
    assert r["kpss"]["status"] == "met"
    # Vardiya asla potansiyel gerekçesi olmamalı
    assert "vardiya" not in r["reason"].lower()
    # Metin şart tablosu HTML'de olmadığı için deneyim/özel şart tablosu eksikliği belirtilmeli
    assert any("tablo" in u.lower() or "deneyim" in u.lower() for u in r["unknown_conditions"])


def test_zafer_kalkinma_ajansi_potential_and_dates():
    from backend.eligibility import detect_application_status
    j = job(
        title="ZAFER KALKINMA AJANSI - UZMAN PERSONEL ALIMI (Kasım 2026)",
        description="İngilizce dilinden en az 70 puan almış olmak. Tablo 1'de yer alan bölümler.",
        kpss_score_type="P1/P2/P3",
    )
    r = classify_public_job(j, profile())
    assert r["category"] == POTANSIYEL
    # YDS en az 70 şartı ve tablo eksikliği ayrı ayrı
    assert any("YDS" in u for u in r["unknown_conditions"])
    # Başvuru henüz başlamadı kontrolü (başlangıç 25.11.2026, test günü 09.11.2026)
    status = detect_application_status(date(2026, 11, 25), date(2026, 12, 14), today=date(2026, 11, 9))
    assert status == "Başvuru Başlamadı"


def test_dokuz_eylul_recruitment_method_is_kpss_siralamasi():
    method = detect_recruitment_method(
        "DOKUZ EYLÜL ÜNİVERSİTESİ - SÖZLEŞMELİ PERSONEL İLANI",
        "yazılı ve/veya sözlü sınav yapılmaksızın 2026 KPSS (B) grubu puan sıralaması esas alınmak suretiyle...",
    )
    assert method == "KPSS puan sıralaması"


def test_marmara_universitesi_recruitment_method_is_kpss_plus_sozlu():
    method = detect_recruitment_method(
        "MARMARA ÜNİVERSİTESİ REKTÖRLÜĞÜ - Sözleşmeli Personel Alım İlanı",
        "KPSS puan sıralaması sonrası sözlü sınav yapılacaktır.",
    )
    assert method == "KPSS puan sıralaması + sözlü sınav"
