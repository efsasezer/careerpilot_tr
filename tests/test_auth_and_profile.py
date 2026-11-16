from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import main
from backend.database import Base
from backend.models import CandidateProfile
from backend.schemas import ProfileUpdate


def test_profile_update_persists_all_fields_to_database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        # Initial profile
        initial = CandidateProfile(
            id=1,
            degree="Lisans",
            department="Bilgisayar Mühendisliği",
            university="İstanbul Topkapı Üniversitesi",
            kpss_p3=87.60,
            accepts_shifts=True,
            preferred_locations="Türkiye geneli",
        )
        session.add(initial)
        session.commit()

        # Update profile
        update_data = ProfileUpdate(
            degree="Lisans",
            department="Yazılım Mühendisliği",
            university="Boğaziçi Üniversitesi",
            kpss_score_type="P3",
            kpss_p3=92.50,
            preferred_locations="Ankara, İstanbul",
            accepts_shifts=False,
            yds_score=85.0,
            age=25,
            driver_license=True,
            experience_years=3.0,
            has_internship=True,
            internship_description="Savunma sanayii stajı",
            certificates="AWS Certified Developer",
            programming_language_evidence="Python, TypeScript",
            skills="FastAPI, React",
            notes="Güncellenmiş aday profili",
        )

        result = main.update_profile(update_data, db=session)

        assert result.department == "Yazılım Mühendisliği"
        assert result.university == "Boğaziçi Üniversitesi"
        assert result.kpss_p3 == 92.50
        assert result.accepts_shifts is False
        assert result.experience_years == 3.0
        assert result.yds_score == 85.0
        assert result.driver_license is True
        assert result.preferred_locations == "Ankara, İstanbul"
        assert result.notes == "Güncellenmiş aday profili"

        # Verify from direct query
        db_profile = session.query(CandidateProfile).filter(CandidateProfile.id == 1).first()
        assert db_profile.department == "Yazılım Mühendisliği"
        assert db_profile.kpss_p3 == 92.50
        assert db_profile.yds_score == 85.0
        assert db_profile.certificates == "AWS Certified Developer"
