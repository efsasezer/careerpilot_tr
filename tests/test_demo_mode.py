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


def build_request(method, path):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    })


def test_read_only_demo_allows_get_requests_and_blocks_write_routes(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)

    async def call_next(_request):
        return Response(status_code=204)

    for path in ("/profile", "/public/matches", "/jobs", "/sources/sync-all"):
        response = asyncio.run(main.restrict_demo_api(build_request("GET", path), call_next))
        assert response.status_code == 204

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = asyncio.run(main.restrict_demo_api(build_request(method, "/jobs"), call_next))
        assert response.status_code == 404

    response = asyncio.run(main.restrict_demo_api(build_request("POST", "/sources/sync-all"), call_next))
    assert response.status_code == 404

    response = asyncio.run(main.restrict_demo_api(build_request("GET", "/public/summary"), call_next))
    assert response.status_code == 204


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
