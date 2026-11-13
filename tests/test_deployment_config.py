from pathlib import Path
import sqlite3

from backend import migrate


def test_migration_uses_configured_render_sqlite_path(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:////var/data/careerpilot.db")

    assert migrate.migration_database_path() == Path("/var/data/careerpilot.db")


def test_migration_skips_memory_and_non_sqlite_databases(monkeypatch):
    monkeypatch.setattr(migrate, "DATABASE_URL", "sqlite:///:memory:")
    assert migrate.migration_database_path() is None

    monkeypatch.setattr(migrate, "DATABASE_URL", "postgresql://example/db")
    assert migrate.migration_database_path() is None


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
