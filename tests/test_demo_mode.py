import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from backend import main
from backend.database import Base
from backend.models import Job


def test_health_reports_read_only_demo_status(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)

    assert main.health()["demo_mode"] is True


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


async def call_app(method, path, headers=()):
    messages = []
    request_sent = False
    raw_path = path.encode("ascii")

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await main.app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": raw_path,
            "query_string": b"",
            "root_path": "",
            "headers": [(name.lower().encode("ascii"), value.encode("ascii")) for name, value in headers],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    return messages


def test_read_only_demo_allows_get_requests_and_blocks_write_routes(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "test-private-access-token")

    async def call_next(_request):
        return Response(status_code=204)

    for path in ("/profile", "/public/matches", "/jobs", "/sources/sync-all"):
        response = asyncio.run(main.restrict_demo_api(build_request("GET", path, "test-private-access-token"), call_next))
        assert response.status_code == 204

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = asyncio.run(main.restrict_demo_api(build_request(method, "/jobs", "test-private-access-token"), call_next))
        assert response.status_code == 404

    response = asyncio.run(main.restrict_demo_api(build_request("POST", "/sources/sync-all", "test-private-access-token"), call_next))
    assert response.status_code == 404

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/public/summary", "test-private-access-token"), call_next))
    assert response.status_code == 204


def test_demo_requires_access_token_for_private_get_routes(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "test-private-access-token")

    async def call_next(_request):
        return Response(status_code=204)

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile"), call_next))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile", "wrong-token"), call_next))
    assert response.status_code == 401

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/auth/check", "test-private-access-token"), call_next))
    assert response.status_code == 204

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/health"), call_next))
    assert response.status_code == 204


def test_demo_allows_cors_preflight_without_a_bearer_token(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "test-private-access-token")

    messages = asyncio.run(
        call_app(
            "OPTIONS",
            "/profile",
            (
                ("Origin", "https://careerpilot-tr-web.onrender.com"),
                ("Access-Control-Request-Method", "GET"),
                ("Access-Control-Request-Headers", "authorization"),
            ),
        )
    )
    response_start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = dict(response_start["headers"])

    assert response_start["status"] == 200
    assert response_headers[b"access-control-allow-origin"] == b"https://careerpilot-tr-web.onrender.com"
    assert b"GET" in response_headers[b"access-control-allow-methods"]
    assert b"POST" in response_headers[b"access-control-allow-methods"]
    assert b"authorization" in response_headers[b"access-control-allow-headers"].lower()


def test_demo_app_rejects_anonymous_private_get_and_allows_health(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "test-private-access-token")

    health_messages = asyncio.run(call_app("GET", "/health"))
    private_messages = asyncio.run(call_app("GET", "/public/matches"))
    health_response = next(message for message in health_messages if message["type"] == "http.response.start")
    private_response = next(message for message in private_messages if message["type"] == "http.response.start")

    assert health_response["status"] == 200
    assert private_response["status"] == 401


def test_api_cors_is_limited_to_render_web_and_local_vite_origins():
    cors = next(
        middleware for middleware in main.app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )
    allowed_origins = cors.kwargs["allow_origins"]

    assert "https://careerpilot-tr-web.onrender.com" in allowed_origins
    assert "http://localhost:5173" in allowed_origins
    assert "http://127.0.0.1:5173" in allowed_origins
    assert "*" not in allowed_origins


def test_demo_fails_closed_when_access_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.delenv("CAREERPILOT_ACCESS_TOKEN", raising=False)

    async def call_next(_request):
        return Response(status_code=204)

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/profile", "some-token"), call_next))
    assert response.status_code == 503


def test_read_only_api_route_functions_expose_complete_local_views():
    from backend.database import SessionLocal

    with SessionLocal() as db:
        profile = main.get_profile(db)
        matches = main.public_matches(db)
        jobs = main.list_jobs(sector="public", category=None, db=db)
        sources = main.list_sources(db)

    assert profile.kpss_p3 == 87.6
    assert len(jobs) == 108
    assert matches["jobs"]
    assert (
        matches["counts"]["UYGUN"]
        + matches["counts"]["POTANSİYEL OLARAK UYGUN"]
        + matches["counts"]["UYGUN DEĞİL"]
        == matches["counts"]["total"]
    )
    assert sources


def test_demo_api_access_control_and_read_only_http_methods(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setenv("CAREERPILOT_ACCESS_TOKEN", "integration-test-token")

    async def call_next(_request):
        return Response(status_code=204)

    token = "integration-test-token"
    for path in ("/profile", "/public/matches", "/jobs", "/sources"):
        response = asyncio.run(main.restrict_demo_api(build_request("GET", path, token), call_next))
        assert response.status_code == 204

    for method, path in (("PUT", "/profile"), ("POST", "/jobs"), ("DELETE", "/jobs/1")):
        response = asyncio.run(main.restrict_demo_api(build_request(method, path, token), call_next))
        assert response.status_code == 404


def test_demo_public_summary_and_listings_are_lightweight():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(Job(
            sector="public",
            title="Örnek kamu ilanı",
            organization="Örnek kurum",
            source_name="Kariyer Kapısı",
            source_url="https://example.gov.tr/ilan",
            description="Uzun ilan metni gizli tutulmalı.",
        ))
        db.commit()
        summary = main.public_summary(db)
        listings = main.public_listings(limit=2, offset=0, db=db)

    assert summary["total"] == 1
    assert summary["open"] == 0
    assert len(summary["latest"]) == 1
    assert listings["total"] == 1
    assert len(listings["items"]) == 1
    assert listings["items"][0]["application_status"] == "Tarih belirtilmemiş"
    assert "description" not in listings["items"][0]
    assert listings["items"][0]["source_name"] == "Kariyer Kapısı"


def test_public_application_status_does_not_assume_unknown_dates_are_open():
    today = main.date.today()

    assert main.public_application_status(None, None, today) == "Tarih belirtilmemiş"
    assert main.public_application_status(today, today, today) == "Başvuru Açık"
    assert main.public_application_status(main.date.fromordinal(today.toordinal() + 1), None, today) == "Başvuru Başlamadı"
    assert main.public_application_status(None, main.date.fromordinal(today.toordinal() - 1), today) == "Başvuru Sona Erdi"
