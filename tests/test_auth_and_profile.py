import asyncio
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from backend import main
from backend.database import Base
from backend.models import CandidateProfile
from backend.schemas import ProfileUpdate


def build_request(method, path, access_token=None):
    headers = []
    if access_token is not None:
        headers.append((b"authorization", f"Bearer {access_token}".encode("ascii")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    })


def test_auth_middleware_in_normal_mode(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", False)
    monkeypatch.delenv("CAREERPILOT_READ_ONLY", raising=False)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "valid-secret-token")

    async def call_next(_request):
        return Response(content=b'{"ok": true}', status_code=200, media_type="application/json")

    # Missing token -> 401
    resp_missing = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile"), call_next))
    assert resp_missing.status_code == 401
    assert resp_missing.headers["www-authenticate"] == "Bearer"
    body_missing = json.loads(resp_missing.body)
    assert "geçerli erişim anahtarı gerekli" in body_missing["detail"]

    # Wrong token -> 401
    resp_wrong = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile", "bad-token"), call_next))
    assert resp_wrong.status_code == 401
    body_wrong = json.loads(resp_wrong.body)
    assert "geçerli erişim anahtarı gerekli" in body_wrong["detail"]

    # Valid token on GET -> 200
    resp_valid = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile", "valid-secret-token"), call_next))
    assert resp_valid.status_code == 200

    # Valid token on PUT (write) in normal mode -> 200 (allowed!)
    resp_put = asyncio.run(main.restrict_demo_api(build_request("PUT", "/profile", "valid-secret-token"), call_next))
    assert resp_put.status_code == 200

    # /auth/check endpoint with valid token -> 200
    resp_auth_check = asyncio.run(main.restrict_demo_api(build_request("GET", "/auth/check", "valid-secret-token"), call_next))
    assert resp_auth_check.status_code == 200

    # Health check is public -> 200 without token
    resp_health = asyncio.run(main.restrict_demo_api(build_request("GET", "/health"), call_next))
    assert resp_health.status_code == 200


def test_auth_middleware_fails_closed_when_token_unset(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", False)
    monkeypatch.delenv("CAREERPILOT_ACCESS_TOKEN", raising=False)

    async def call_next(_request):
        return Response(status_code=200)

    resp = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile", "any-token"), call_next))
    assert resp.status_code == 503
    body = json.loads(resp.body)
    assert "yapılandırılmamış" in body["detail"]


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
