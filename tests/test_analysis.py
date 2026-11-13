from backend.analysis import extract_skills, skill_frequency, check_public_score_fit


def test_extract_skills_recognizes_common_skills():
    assert set(extract_skills("Python, SQL, Apache Airflow ve Docker bilgisi")) == {"python", "sql", "airflow", "docker"}


def test_skill_frequency_counts_jobs_not_repetitions():
    jobs = [
        {"title": "Data Analyst", "skills": "Python, SQL", "description": "Python"},
        {"title": "BI Analyst", "skills": "SQL, Power BI", "description": ""},
    ]
    result = {row["skill"]: row for row in skill_frequency(jobs)}
    assert result["python"]["count"] == 1
    assert result["sql"]["count"] == 2
    assert result["sql"]["percentage"] == 100.0


def test_public_score_check_is_only_preliminary_score_check():
    job = {"kpss_score_type": "P3", "kpss_min_score": 75}
    profile = {"kpss_p3": 87.6}
    assert "diğer tüm şartlar" in check_public_score_fit(job, profile)
