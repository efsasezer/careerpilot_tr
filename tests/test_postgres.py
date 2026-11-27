"""Gerçek PostgreSQL testleri. Yalnızca CAREERPILOT_TEST_POSTGRES_URL tanımlıysa çalışır:

    docker run -d --name careerpilot-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
    CAREERPILOT_TEST_POSTGRES_URL=postgresql://postgres:test@localhost:55432/postgres pytest tests/test_postgres.py
"""

import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text

from backend import dbtools
from backend.database import make_engine
from backend.models import Job

ADMIN_URL = os.getenv("CAREERPILOT_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="CAREERPILOT_TEST_POSTGRES_URL tanımlı değil")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def database_url():
    name = f"cp_test_{uuid.uuid4().hex[:10]}"
    admin = make_engine(ADMIN_URL).execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    yield ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _sqlite_with_data(tmp_path):
    from backend.migrate import migrate
    from sqlalchemy.orm import Session

    source = make_engine(f"sqlite:///{tmp_path / 'source.db'}")
    migrate(source)
    with Session(source) as db:
        db.add(Job(sector="public", title="Türkçe ğüşiöç İlan", organization="Kurum", description="metin\x00NUL içerir"))
        db.commit()
    return source


def test_sqlite_to_postgres_copy_is_verified_and_refuses_nonempty_target(tmp_path, monkeypatch, database_url):
    monkeypatch.setenv("CAREERPILOT_DB_AUTOCREATE", "true")
    source, target = _sqlite_with_data(tmp_path), make_engine(database_url)
    outcome = dbtools.copy(source, target)
    assert outcome["counts"]["jobs"] == 1
    assert dbtools.snapshot(source)["digests"] == dbtools.snapshot(target)["digests"]
    with target.connect() as connection:
        assert connection.execute(text("SELECT description FROM jobs")).scalar() == "metinNUL içerir"
    from sqlalchemy.orm import Session

    with Session(target) as db:  # kimlik sayacı aktarılan en büyük kimlikten devam eder
        added = Job(sector="public", title="yeni")
        db.add(added)
        db.commit()
        assert added.id == 2
    with pytest.raises(RuntimeError, match="boş değil"):
        dbtools.copy(source, target)


def test_backup_and_restore_round_trip(tmp_path, monkeypatch, database_url):
    monkeypatch.setenv("CAREERPILOT_DB_AUTOCREATE", "true")
    source, target = _sqlite_with_data(tmp_path), make_engine(database_url)
    dbtools.copy(source, target)
    path = str(tmp_path / "yedek.json.gz")
    dbtools.write_backup(target, path)
    restored = make_engine(f"sqlite:///{tmp_path / 'restored.db'}")
    dbtools.restore(dbtools.read_backup(path), restored)
    assert dbtools.snapshot(restored)["digests"] == dbtools.snapshot(target)["digests"]


def test_application_end_to_end_on_postgres(database_url):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "pg_smoke.py")], capture_output=True, text=True, timeout=300,
        env={**os.environ, "DATABASE_URL": database_url},
    )
    assert "PG_SMOKE_OK" in completed.stdout, completed.stdout[-1500:] + completed.stderr[-3000:]
