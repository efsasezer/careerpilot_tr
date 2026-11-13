"""
Güvenli veritabanı migration scripti.
Mevcut verileri KORUR, yalnızca eksik sütunları ekler.
"""

import sqlite3
from pathlib import Path

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

    # --- jobs tablosu ---
    print("\n[jobs tablosu]")
    add_column_if_missing(cursor, "jobs", "source_name", "TEXT", default="''")
    add_column_if_missing(cursor, "jobs", "application_start", "DATE")
    add_column_if_missing(cursor, "jobs", "quota", "TEXT", default="''")
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
    conn.close()
    print("\nMigration tamamlandı.")


if __name__ == "__main__":
    migrate()
