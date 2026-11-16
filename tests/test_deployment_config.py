from pathlib import Path
import sqlite3

from backend import migrate
from backend.database import ensure_sqlite_database_file_exists


def test_render_api_requires_password_and_session_secret_without_demo_mode():
    config = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")

    assert config.count("    name: careerpilot-tr-api\n    runtime: python") == 1
    assert "--proxy-headers" in config  # Render vekilinin arkasında HTTPS ve gerçek istemci adresi
    assert "healthCheckPath: /health" in config
    assert "CAREERPILOT_DEMO_MODE" not in config and "CAREERPILOT_ACCESS_TOKEN" not in config
    # Şifre depoya yazılmaz: Render panelinden girilir. Oturum anahtarını Render üretir.
    assert "      - key: CAREERPILOT_PASSWORD\n        sync: false" in config
    assert "      - key: CAREERPILOT_SESSION_SECRET\n        generateValue: true" in config


def test_render_static_site_proxies_api_on_the_same_origin():
    config = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(encoding="utf-8")

    assert config.count("  - type: web") == 2
    assert "    name: careerpilot-tr-web\n    runtime: static" in config
    assert "streamlit" not in config.casefold()
    assert "    buildCommand: npm ci && npm run build" in config
    # Çerezin birinci taraf olması için API aynı alan adından /api altında sunulur.
    assert "        source: /api/*\n        destination: https://careerpilot-tr-api.onrender.com/*" in config
    assert config.index("source: /api/*") < config.index("source: /*\n")
    assert "      - type: rewrite\n        source: /*\n        destination: /index.html" in config


def test_streamlit_client_and_its_dependencies_are_gone():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8").casefold()

    assert not (root / "frontend" / "app.py").exists()
    assert not (root / "legacy").exists()
    assert "streamlit" not in requirements and "pandas" not in requirements


def test_migration_uses_configured_render_sqlite_path(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:////var/data/careerpilot.db")

    assert migrate.migration_database_path() == Path("/var/data/careerpilot.db")


def test_migration_skips_memory_and_non_sqlite_databases(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:///:memory:")
    assert migrate.migration_database_path() is None

    monkeypatch.setattr(migrate, "DATABASE_URL", "postgresql://example/db")
    assert migrate.migration_database_path() is None


def test_missing_sqlite_database_is_not_silently_created(tmp_path, monkeypatch):
    monkeypatch.delenv("CAREERPILOT_DB_AUTOCREATE", raising=False)
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


def test_missing_sqlite_uri_database_is_not_silently_created(tmp_path, monkeypatch):
    monkeypatch.delenv("CAREERPILOT_DB_AUTOCREATE", raising=False)
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
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'source_listings'"
        ).fetchone() == ("source_listings",)

    backups = list(tmp_path.glob("careerpilot.db.backup.*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT title FROM jobs WHERE id = 1").fetchone() == ("Mevcut ilan",)
