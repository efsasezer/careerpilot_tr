from backend.eligibility import build_candidate_profile, classify_public_job

UYGUN = "UYGUN"
POTANSIYEL = "POTANSİYEL OLARAK UYGUN"
DEGIL = "UYGUN DEĞİL"


def profile(**extra):
    return build_candidate_profile({
        "degree": "Lisans", "department": "Bilgisayar Mühendisliği", "kpss_p3": 87.60, **extra,
    })


def job(description="", **fields):
    return {"title": "Uzman", "description": description, **fields}


def test_4001_is_eligible_without_department_text():
    r = classify_public_job(job(qualification_codes="4001", kpss_score_type="P3", kpss_min_score=80), profile())
    assert r["category"] == UYGUN
    assert r["education"]["status"] == "met"


def test_4001_ignores_year_like_numbers_in_code_line():
    r = classify_public_job(job("Nitelik Kodları: 4001 (2024 kılavuzu)"), profile())
    assert r["qualification_codes"] == ["4001"]


def test_computer_engineering_named_is_eligible():
    r = classify_public_job(job(
        "Bilgisayar Mühendisliği bölümlerinden mezun olmak. KPSS P3 puanı en az 70 olmalıdır."), profile())
    assert r["education"]["status"] == "met"
    assert r["kpss"]["status"] == "met"
    assert r["category"] == UYGUN


def test_computer_engineering_in_a_list_of_engineerings():
    r = classify_public_job(job(
        "Elektrik-Elektronik, Bilgisayar ve Endüstri Mühendisliği bölümlerinden mezun olmak."), profile())
    assert r["education"]["status"] == "met"


def test_generic_engineering_departments_accept_computer_engineering():
    r = classify_public_job(job(
        "Mühendislik fakültelerinin ilgili bölümlerinden mezun olmak. "
        "YDS'den en az 60 puan almış olmak. KPSS P3 puanı en az 80 olmalıdır."), profile())
    assert r["education"]["status"] == "met"
    assert r["category"] == POTANSIYEL
    assert any("YDS" in item for item in r["unknown_conditions"])


def test_only_environmental_engineering_is_not_eligible():
    r = classify_public_job(job("Çevre Mühendisliği bölümünden mezun olmak."), profile())
    assert r["education"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_named_list_without_computer_engineering_is_not_eligible():
    r = classify_public_job(job(
        "Kabul edilen bölümler: İnşaat Mühendisliği, Harita Mühendisliği, İktisat. "
        "Bu bölümlerden mezun olmak."), profile())
    assert r["category"] == DEGIL


def test_software_engineering_only_stays_potential():
    r = classify_public_job(job("Yazılım Mühendisliği bölümünden mezun olmak."), profile())
    assert r["education"]["status"] == "unknown"
    assert r["category"] == POTANSIYEL


def test_law_faculty_is_not_eligible():
    r = classify_public_job(job("Hukuk fakültesi mezunu olmak. Avukatlık ruhsatı sahibi olmak."), profile())
    assert r["category"] == DEGIL


def test_unreadable_department_is_potential_not_rejected():
    r = classify_public_job(job("Kabul edilen bölümler ekteki tabloda yer almaktadır."), profile())
    assert r["category"] == POTANSIYEL
    assert r["education"]["status"] == "unknown"


def test_general_public_conditions_do_not_create_unknowns():
    r = classify_public_job(job(
        "Bilgisayar Mühendisliği bölümlerinden mezun olmak. Türk vatandaşı olmak. "
        "Askerlikle ilişiği bulunmamak. Adli sicil kaydı temiz olmak. "
        "657 sayılı Kanun'un 48. maddesindeki şartları taşımak. Güvenlik soruşturması ve arşiv araştırması yapılacaktır.",
        kpss_score_type="P3", kpss_min_score=70), profile())
    assert r["category"] == UYGUN
    assert r["unknown_conditions"] == []
    assert "Türk vatandaşı olmak" in r["general_conditions"]
    assert "Güvenlik soruşturması (kurum yürütür)" in r["general_conditions"]


def test_preference_statements_are_not_mandatory():
    r = classify_public_job(job(
        "Bilgisayar Mühendisliği bölümlerinden mezun olmak. Tercihen yüksek lisans yapmış olmak. "
        "İkinci yabancı dil bilmek tercih sebebidir. Belirli bir alanda deneyim sahibi olmak puanlamada avantaj sağlar. "
        "Tercihen CISSP sertifikasına sahip olmak. Tercihen B sınıfı sürücü belgesine sahip olmak.",
        kpss_score_type="P3", kpss_min_score=70), profile())
    assert r["unknown_conditions"] == []
    assert r["category"] == UYGUN


def test_p3_below_minimum_is_not_eligible():
    r = classify_public_job(job("Bilgisayar Mühendisliği mezunu olmak.", kpss_score_type="P3", kpss_min_score=90), profile())
    assert r["kpss"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_p1_or_p2_only_requirement_is_potential_without_those_scores():
    r = classify_public_job(job("Bilgisayar Mühendisliği mezunu olmak.", kpss_score_type="P1/P2", kpss_min_score=70), profile())
    assert r["kpss"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_kpss_is_evaluated_separately_from_department():
    r = classify_public_job(job("Hukuk fakültesi mezunu olmak.", kpss_score_type="P3", kpss_min_score=70), profile())
    assert r["kpss"]["status"] == "met"
    assert r["education"]["status"] == "not_met"
    assert r["category"] == DEGIL


def test_no_invented_minimum_score():
    r = classify_public_job(job("Bilgisayar Mühendisliği mezunu olmak.", kpss_score_type="P3"), profile())
    assert r["kpss"]["minimum_score"] is None


def test_unknown_experience_and_yds_make_it_potential():
    r = classify_public_job(job(
        "Bilgisayar Mühendisliği mezunu olmak. En az 3 yıl deneyim sahibi olmak. YDS'den en az 70 puan almak.",
        kpss_score_type="P3", kpss_min_score=70), profile())
    assert r["category"] == POTANSIYEL
    names = {item["name"]: item["status"] for item in r["requirements"]}
    assert names["Deneyim"] == "unknown" and names["YDS"] == "unknown" and names["Eğitim"] == "met"


def test_known_experience_and_yds_in_profile_are_used():
    desc = "Bilgisayar Mühendisliği mezunu olmak. En az 3 yıl deneyim sahibi olmak. YDS'den en az 70 puan almak."
    ok = classify_public_job(job(desc, kpss_score_type="P3", kpss_min_score=70), profile(experience_years=4, yds_score=75))
    assert ok["category"] == UYGUN
    low = classify_public_job(job(desc, kpss_score_type="P3", kpss_min_score=70), profile(experience_years=1, yds_score=75))
    assert low["category"] == DEGIL


def test_shift_preference_is_taken_from_profile():
    desc = "Bilgisayar Mühendisliği mezunu olmak. Vardiyalı çalışmaya uygun olmak."
    assert classify_public_job(job(desc), profile(accepts_shifts=True))["category"] == UYGUN
    assert classify_public_job(job(desc), profile())["category"] == POTANSIYEL
    assert classify_public_job(job(desc), profile(accepts_shifts=False))["category"] == DEGIL


def test_minimum_age_18_is_general_not_an_age_limit():
    r = classify_public_job(job("Bilgisayar Mühendisliği mezunu olmak. 18 yaşını doldurmuş olmak."), profile())
    assert r["category"] == UYGUN


def test_repeated_requirement_is_listed_once():
    sentence = "Bilgisayar Mühendisliği bölümlerinden mezun olmak. En az 3 yıl deneyim sahibi olmak."
    r = classify_public_job(job(f"{sentence}\n{sentence}"), profile())
    assert r["education"]["requirement"].count("mezun olmak") == 1
    assert sum("deneyim" in item for item in r["unknown_conditions"]) == 1


def test_profile_fields_reach_the_candidate_dict():
    p = profile(yds_score=70, age=30, driver_license=True, experience_years=2,
                certificates="CCNA", programming_language_evidence="Python, Java", accepts_shifts=True)
    assert (p["yds_score"], p["age"], p["driver_license"], p["experience_years"]) == (70, 30, True, 2)
    assert p["programming_language_evidence"] == "Python, Java" and p["accepts_shifts"] is True
    assert build_candidate_profile({})["yds_score"] is None