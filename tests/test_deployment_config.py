from pathlib import Path
import sqlite3

from backend import migrate
from backend.database import ensure_sqlite_database_file_exists


def test_render_uses_default_database_without_a_persistent_disk():
    config = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")

    assert "plan: free" in config
    assert config.count("    name: careerpilot-tr-api") == 1
    assert "startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT" in config
    assert "healthCheckPath: /health" in config
    assert "CAREERPILOT_DEMO_MODE" in config
    assert "DATABASE_URL" not in config
    assert "\n    disk:" not in config


def test_render_defines_separate_free_frontend_for_existing_api():
    config = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")

    assert config.count("  - type: web") == 2
    assert config.count("    name: careerpilot-tr-api") == 1
    assert config.count("    name: careerpilot-tr-frontend") == 1
    assert config.count("    plan: free") == 2
    assert "startCommand: streamlit run frontend/app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true" in config
    assert "healthCheckPath: /_stcore/health" in config
    assert "      - key: API_URL\n        value: https://careerpilot-tr-api.onrender.com" in config
    assert "      - key: CAREERPILOT_DEMO_MODE\n        value: \"true\"" in config


def test_migration_uses_configured_render_sqlite_path(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:////var/data/careerpilot.db")

    assert migrate.migration_database_path() == Path("/var/data/careerpilot.db")


def test_migration_skips_memory_and_non_sqlite_databases(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:///:memory:")
    assert migrate.migration_database_path() is None

    monkeypatch.setattr(migrate, "DATABASE_URL", "postgresql://example/db")
    assert migrate.migration_database_path() is None


def test_missing_sqlite_database_is_not_silently_created(tmp_path):
    missing_database = tmp_path / "missing.db"

    try:
        ensure_sqlite_database_file_exists(f"sqlite:///{missing_database.as_posix()}")
    except FileNotFoundError as error:
        assert str(missing_database) in str(error)
    else:
        raise AssertionError("Missing SQLite database should raise FileNotFoundError")

    assert not missing_database.exists()


def test_memory_sqlite_database_does_not_require_a_file():
    ensure_sqlite_database_file_exists("sqlite:///:memory:")


def test_missing_sqlite_uri_database_is_not_silently_created(tmp_path):
    missing_database = tmp_path / "missing.db"
    database_url = f"sqlite:///file:{missing_database.as_posix()}?uri=true"

    try:
        ensure_sqlite_database_file_exists(database_url)
    except FileNotFoundError as error:
        assert str(missing_database) in str(error)
    else:
        raise AssertionError("Missing SQLite URI database should raise FileNotFoundError")

    assert not missing_database.exists()


def test_migration_preserves_existing_database_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "careerpilot.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT)")
        connection.execute("CREATE TABLE candidate_profile (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO jobs (id, title) VALUES (1, 'Mevcut ilan')")
        connection.execute("INSERT INTO candidate_profile (id) VALUES (1)")

    monkeypatch.setattr(migrate, "DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    migrate.migrate()

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT title FROM jobs WHERE id = 1").fetchone() == ("Mevcut ilan",)
        assert connection.execute("SELECT id FROM candidate_profile WHERE id = 1").fetchone() == (1,)
