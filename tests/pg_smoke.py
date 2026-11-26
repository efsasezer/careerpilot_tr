"""PostgreSQL üzerinde uçtan uca duman testi. `DATABASE_URL` boş bir PostgreSQL veritabanını göstermelidir.

Doğrudan çalıştırılır: `DATABASE_URL=postgresql://... python tests/pg_smoke.py`
(tests/test_postgres.py bunu, CAREERPILOT_TEST_POSTGRES_URL tanımlıysa ayrı bir süreçte çalıştırır.)
"""

from datetime import date, datetime, timedelta
import os
import sys

os.environ.setdefault("CAREERPILOT_PASSWORD", "pg-smoke-password")
os.environ.setdefault("CAREERPILOT_SESSION_SECRET", "s" * 40)
os.environ["CAREERPILOT_DISABLE_SCHEDULER"] = "true"
os.environ["CAREERPILOT_DISABLE_RESULT_CHECK"] = "true"
os.environ["CAREERPILOT_NOTIFY_DISABLED"] = "true"
os.environ["CAREERPILOT_SOURCE_REQUEST_DELAY_SECONDS"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from backend import main, migrate, sync  # noqa: E402
from backend.database import SessionLocal, engine  # noqa: E402
from backend.models import Job, JobEvent, Notification, SourceListing, SourceSyncHistory, UserJobState, UserVerification  # noqa: E402

assert engine.dialect.name == "postgresql", "Bu test yalnızca PostgreSQL üzerinde çalışır."
today = date.today()


class FakeSource:
    source_name = "Deneme Kaynağı"
    pages_checked = 1

    def __init__(self, fail=False):
        self.fail = fail

    def fetch_listings(self):
        if self.fail:
            from backend.sources.base import SourceFetchError

            raise SourceFetchError(self.source_name, "https://ornek.gov.tr/", "Kaynak sayfası alınamadı.", 403)
        return [{
            "source_key": "deneme", "source_name": self.source_name, "source_url": "https://ornek.gov.tr/",
            "detail_url": "https://ornek.gov.tr/ilan/1", "external_id": "1", "title": "5 Memur Alım İlanı",
            "institution": "Örnek Kurumu", "application_start_date": (today - timedelta(days=1)).isoformat(),
            "application_end_date": (today + timedelta(days=9)).isoformat(), "content_hash": "h1",
        }]

    def fetch_detail(self, url):
        text = ("Herhangi bir lisans programından mezun olmak. KPSS P3 puan türünden en az 60 puan almış olmak. "
                f"Sınav {(today + timedelta(days=20)):%d.%m.%Y} tarihinde yapılacaktır. " * 3)
        return {"source_text": text, "content_hash": "d1", "detail_url": url}


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


# 1. Göç yeniden çalıştırılabilir
assert migrate.migrate(engine)["changed"] is False

with SessionLocal() as db:
    # 2. Tarama: aynı tarama iki kez → mükerrer ilan ya da olay yok
    first = sync.run_sync_locked(db, registry={"deneme": FakeSource()}, scan_documents=False)
    assert first["results"]["deneme"]["imported"] == 1, first
    jobs, events = count(db, Job), count(db, JobEvent)
    second = sync.run_sync_locked(db, registry={"deneme": FakeSource()}, scan_documents=False)
    assert second["results"]["deneme"]["imported"] == 0
    assert (count(db, Job), count(db, JobEvent), count(db, SourceListing)) == (jobs, events, 1)
    job_id = db.scalar(select(Job.id))

    # 3. Kilit: tarama sürerken ikinci tarama başlamaz; süresi dolan kilit devralınır
    assert sync.acquire_scan_lock(db, "a")
    with SessionLocal() as other:
        assert not sync.acquire_scan_lock(other, "b")
        try:
            sync.run_sync_locked(other, registry={"deneme": FakeSource()}, scan_documents=False)
            raise AssertionError("ikinci tarama başlamamalıydı")
        except sync.ScanAlreadyRunning:
            pass
        assert sync.acquire_scan_lock(other, "b", now=datetime.now() + sync.LOCK_LEASE + timedelta(minutes=1))
        sync.release_scan_lock(other, "b")

with TestClient(main.app) as client:
    assert client.get("/matches").status_code == 401
    assert client.post("/auth/login", json={"password": os.environ["CAREERPILOT_PASSWORD"]}).status_code == 200
    assert client.get("/health").json()["storage"] == {"backend": "postgresql", "durable": True, "warning": None}

    # 4. Kullanıcı işlemleri kalıcı ve geri alınabilir
    for tracking in ("saved", "applied", "", "hidden", ""):
        assert client.patch(f"/jobs/{job_id}/tracking", json={"tracking": tracking, "notes": "not"}).status_code == 200
        positions = [item for item in client.get("/matches").json()["jobs"] if item["parent_job_id"] == job_id]
        assert positions and all(item["tracking"] == tracking for item in positions), tracking
    assert client.put(f"/jobs/{job_id}/verification", json={"decision": "not_eligible", "note": "elle"}).status_code == 200
    assert client.put(f"/jobs/{job_id}/verification", json={"decision": "eligible"}).status_code == 200  # tekrar değiştirilebilir
    assert client.patch(f"/jobs/{job_id}/tracking", json={"tracking": "saved"}).status_code == 200

    # 5. Yeniden tarama ve başarısız kaynak kullanıcı verisine ve ilanlara dokunmaz
    with SessionLocal() as db:
        sync.run_sync_locked(db, registry={"deneme": FakeSource()}, scan_documents=False)
        failed = sync.run_sync_locked(db, registry={"deneme": FakeSource(fail=True)}, scan_documents=False)
        assert failed["results"]["deneme"]["status"] == "error"
        assert count(db, Job) == jobs and db.get(UserJobState, job_id).tracking == "saved"
        assert db.scalar(select(UserVerification.decision).where(UserVerification.job_id == job_id)) == "eligible"
        last = db.scalar(select(SourceSyncHistory).order_by(SourceSyncHistory.id.desc()).limit(1))
        assert (last.status, last.error_kind) == ("error", "http_403") and last.origin
    detail = client.get(f"/jobs/{job_id}/detail").json()
    assert detail["tracking"] == "saved" and detail["job_verification"]["decision"] == "eligible"
    assert any(event["kind"] == "exam" for event in detail["events"])

    # 6. Takvim, görevler, bildirimler
    start, end = today.isoformat(), (today + timedelta(days=30)).isoformat()
    kinds = {event["kind"] for event in client.get(f"/calendar?start={start}&end={end}").json()["events"]}
    assert {"application_deadline", "exam"} <= kinds, kinds
    task = client.post("/tasks", json={"title": "Belgeleri hazırla", "task_date": start}).json()
    assert client.post(f"/tasks/{task['id']}/complete", json={"day": start, "done": True}).status_code == 200
    assert client.get("/notifications").status_code == 200
    with SessionLocal() as db:
        before = count(db, Notification)
    client.get("/notifications")
    with SessionLocal() as db:
        assert count(db, Notification) == before  # yinelenen bildirim yok
    for path in ("/sources", "/results", "/ylsy", "/profile", "/system/status", "/account/kariyer-kapisi"):
        assert client.get(path).status_code == 200, path
    profile = client.get("/profile").json()
    profile.update(department="Bilgisayar Mühendisliği", degree="Lisans", kpss_scores={"P3": 87.5}, ales_score=87)
    assert client.put("/profile", json=profile).status_code == 200
    assert client.get("/profile").json()["kpss_scores"] == {"P3": 87.5}

print("PG_SMOKE_OK")
