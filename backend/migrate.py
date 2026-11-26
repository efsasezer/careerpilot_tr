"""Güvenli, yeniden çalıştırılabilir şema göçü (SQLite ve PostgreSQL).

Kurallar:
- Yalnızca ekleme yapılır: eksik tablo, eksik sütun, eksik indeks. Hiçbir tablo, sütun ya da satır silinmez.
- Her adım "yoksa ekle" biçimindedir; göç kaç kez çalıştırılırsa çalıştırılsın sonuç aynıdır.
- SQLite dosyasında şema değişecekse önce dosyanın yedeği alınır.
- Göçten sonra satır sayıları değişmemiş olmalıdır; değiştiyse hata verilir.
- Uygulanan sürüm `schema_migrations` tablosuna yazılır.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import CreateIndex

SCHEMA_VERSION = 5  # 5: kalıcı tarama kilidi, hata türü/çıkış ortamı, olay kanıtı alanları


def migration_database_path(database_url: str | None = None) -> Path | None:
    from .database import DATABASE_URL

    url = make_url(database_url or DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def _literal_default(column) -> str | None:
    """Eklenen sütunda eski satırların alacağı değer (modeldeki sabit varsayılan)."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def pending_changes(engine: Engine, metadata) -> dict:
    """Modelde olup veritabanında olmayan tablo, sütun ve indeksler."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    changes = {"tables": [], "columns": [], "indexes": []}
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            changes["tables"].append(table.name)
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present:
                changes["columns"].append((table.name, column.name))
        indexed = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in indexed:
                changes["indexes"].append((table.name, index.name))
    return changes


def _backup_sqlite(path: Path) -> Path:
    backup_path = path.with_name(f"{path.name}.backup.{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}")
    source = sqlite3.connect(str(path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def _row_counts(engine: Engine, tables: list[str]) -> dict[str, int]:
    with engine.connect() as connection:
        return {name: connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one() for name in tables}


def migrate(engine: Engine | None = None) -> dict:
    from .database import Base
    from .database import engine as default_engine
    from . import models  # noqa: F401  (tabloların Base'e kaydı)

    engine = engine or default_engine
    metadata = Base.metadata
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    changes = pending_changes(engine, metadata)
    changed = bool(changes["tables"] or changes["columns"] or changes["indexes"])
    report = {"changed": changed, "backup": None, **changes}

    path = migration_database_path(str(engine.url.render_as_string(hide_password=False)))
    if changed and path is not None and path.exists() and existing_tables:
        report["backup"] = str(_backup_sqlite(path))
        print(f"Yapı değişikliğinden önce veritabanı yedeği alındı: {report['backup']}")

    counted = sorted(existing_tables & {table.name for table in metadata.sorted_tables})
    before = _row_counts(engine, counted)

    metadata.create_all(bind=engine)  # yalnızca eksik tabloları oluşturur
    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        for table_name, column_name in changes["columns"]:
            column = metadata.tables[table_name].columns[column_name]
            column_type = column.type.compile(dialect=engine.dialect)
            default = _literal_default(column)
            statement = f"ALTER TABLE {preparer.quote(table_name)} ADD COLUMN {preparer.quote(column_name)} {column_type}"
            if default is not None:
                statement += f" DEFAULT {default}"
                if not column.nullable:
                    statement += " NOT NULL"
            connection.execute(text(statement))
            print(f"  + {table_name}.{column_name} eklendi")
        for table_name, index_name in changes["indexes"]:
            index = next(item for item in metadata.tables[table_name].indexes if item.name == index_name)
            if all(column.name in {c["name"] for c in inspect(connection).get_columns(table_name)} for column in index.columns):
                connection.execute(CreateIndex(index, if_not_exists=True))
        # Eski sürümlerde takip durumu ve notlar ilan tablosundaydı; kullanıcı tablosuna bir kez taşınır.
        job_columns = {column["name"] for column in inspect(connection).get_columns("jobs")} if "jobs" in existing_tables else set()
        if {"tracking", "notes"} <= job_columns:
            connection.execute(text(
                "INSERT INTO user_job_state (job_id, tracking, notes, updated_at) "
                "SELECT j.id, COALESCE(j.tracking, ''), COALESCE(j.notes, ''), CURRENT_TIMESTAMP FROM jobs j "
                "WHERE (COALESCE(j.tracking, '') <> '' OR COALESCE(j.notes, '') <> '') "
                "AND NOT EXISTS (SELECT 1 FROM user_job_state s WHERE s.job_id = j.id)"
            ))
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)"
        ))
        applied = connection.execute(text("SELECT 1 FROM schema_migrations WHERE version = :v"), {"v": SCHEMA_VERSION}).first()
        if applied is None:
            connection.execute(text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                               {"v": SCHEMA_VERSION, "t": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    after = _row_counts(engine, [name for name in counted if name != "user_job_state"])
    lost = {name: (before[name], after[name]) for name in after if after[name] < before[name]}
    if lost:
        raise RuntimeError(f"Göç doğrulaması başarısız: satır sayısı azaldı {lost}")
    if path is not None and path.exists():
        with sqlite3.connect(str(path)) as check:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Göç doğrulaması başarısız: integrity={integrity}")
    return report


if __name__ == "__main__":
    outcome = migrate()
    print("Şema güncel." if not outcome["changed"] else f"Şema güncellendi: {outcome}")
