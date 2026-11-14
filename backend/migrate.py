"""
Güvenli veritabanı migration scripti.
Mevcut verileri KORUR, yalnızca eksik sütunları ekler.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .database import DATABASE_URL


def migration_database_path() -> Path | None:
    url = make_url(DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def add_column_if_missing(cursor, table, column, col_type, default=None):
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        if default is not None:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}")
        else:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"  + {table}.{column} eklendi")
    else:
        print(f"  = {table}.{column} zaten mevcut")


def migrate():
    db_path = migration_database_path()
    if db_path is None:
        print("SQLite olmayan veya bellek içi veritabanı — migration atlanıyor.")
        return
    if not db_path.exists():
        print(f"Veritabanı henüz yok: {db_path} — migration atlanıyor.")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    print(f"\nMigration başlatılıyor: {db_path}")

    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    job_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(jobs)")
    } if "jobs" in tables else set()
    profile_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(candidate_profile)")
    } if "candidate_profile" in tables else set()
    required_job_columns = {
        "source_name", "application_start", "announcement_date", "quota",
        "employment_type", "recruitment_method", "is_employment", "updated_at",
    }
    required_profile_columns = {
        "university", "kpss_score_type", "accepts_shifts", "yds_score", "age",
        "driver_license", "experience_years", "has_internship",
        "internship_description", "certificates", "programming_language_evidence",
        "notes", "updated_at",
    }
    schema_change_needed = (
        not {"source_listings", "source_sync_history"} <= tables
        or not required_job_columns <= job_columns
        or not required_profile_columns <= profile_columns
    )
    if schema_change_needed:
        backup_path = db_path.with_name(
            f"{db_path.name}.backup.{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"
        )
        backup = sqlite3.connect(str(backup_path))
        try:
            conn.backup(backup)
        finally:
            backup.close()
        print(f"Yapı değişikliğinden önce veritabanı yedeği alındı: {backup_path}")

    # --- jobs tablosu ---
    print("\n[jobs tablosu]")
    add_column_if_missing(cursor, "jobs", "source_name", "TEXT", default="''")
    add_column_if_missing(cursor, "jobs", "application_start", "DATE")
    add_column_if_missing(cursor, "jobs", "announcement_date", "DATE")
    add_column_if_missing(cursor, "jobs", "quota", "TEXT", default="''")
    add_column_if_missing(cursor, "jobs", "employment_type", "TEXT", default="''")
    add_column_if_missing(cursor, "jobs", "recruitment_method", "TEXT", default="''")
    add_column_if_missing(cursor, "jobs", "is_employment", "BOOLEAN", default="1")
    add_column_if_missing(cursor, "jobs", "updated_at", "DATETIME")

    # --- candidate_profile tablosu ---
    print("\n[candidate_profile tablosu]")
    add_column_if_missing(cursor, "candidate_profile", "university", "TEXT", default="''")
    add_column_if_missing(cursor, "candidate_profile", "kpss_score_type", "TEXT", default="'P3'")
    add_column_if_missing(cursor, "candidate_profile", "accepts_shifts", "BOOLEAN")
    add_column_if_missing(cursor, "candidate_profile", "yds_score", "REAL")
    add_column_if_missing(cursor, "candidate_profile", "age", "INTEGER")
    add_column_if_missing(cursor, "candidate_profile", "driver_license", "BOOLEAN")
    add_column_if_missing(cursor, "candidate_profile", "experience_years", "REAL")
    add_column_if_missing(cursor, "candidate_profile", "has_internship", "BOOLEAN")
    add_column_if_missing(cursor, "candidate_profile", "internship_description", "TEXT", default="''")
    add_column_if_missing(cursor, "candidate_profile", "certificates", "TEXT", default="''")
    add_column_if_missing(cursor, "candidate_profile", "programming_language_evidence", "TEXT", default="''")
    add_column_if_missing(cursor, "candidate_profile", "notes", "TEXT", default="''")
    add_column_if_missing(cursor, "candidate_profile", "updated_at", "DATETIME")

    conn.commit()
    before_counts = {}
    for table in ("jobs", "candidate_profile"):
        if table in tables:
            before_counts[table] = cursor.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
    conn.close()

    from .models import Base

    migration_engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(bind=migration_engine)
    finally:
        migration_engine.dispose()
    with sqlite3.connect(str(db_path)) as verify:
        integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
        after_counts = {
            table: verify.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before_counts
        }
    if integrity != "ok" or before_counts != after_counts:
        raise RuntimeError(
            "Migration doğrulaması başarısız oldu: "
            f"integrity={integrity}, before={before_counts}, after={after_counts}"
        )
    print("\nMigration tamamlandı.")


if __name__ == "__main__":
    migrate()
