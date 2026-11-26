"""Veritabanı denetimi, yedekleme, geri yükleme ve SQLite → PostgreSQL aktarımı.

    python -m backend.dbtools check   [--url URL]
    python -m backend.dbtools backup  --out yedek.json.gz [--url URL]
    python -m backend.dbtools restore --in yedek.json.gz --url HEDEF
    python -m backend.dbtools copy    --from KAYNAK --to HEDEF

Güvenlik kuralları:
- Kaynak veritabanı yalnızca okunur; hiçbir komut kaynakta değişiklik yapmaz.
- Geri yükleme ve aktarım yalnızca BOŞ bir hedefe yazar. Dolu hedefin üzerine yazma seçeneği yoktur.
- Yazma tek bir işlem (transaction) içinde yapılır; satır sayıları ve içerik özeti kaynağınkiyle
  aynı değilse işlem geri alınır ve hedef boş kalır.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import gzip
from hashlib import sha256
import json
import sys

from sqlalchemy import Boolean, Date, DateTime, func, inspect, select, text
from sqlalchemy.engine import Engine

FORMAT = "careerpilot-backup-1"
# Tarama ve oturum durumunu taşıyan, yedeğe/aktarıma girmeyen tablolar.
TRANSIENT_TABLES = {"user_sessions", "scan_locks"}


def _metadata():
    from .database import Base
    from . import models  # noqa: F401

    return Base.metadata


def _tables(include_transient: bool = False):
    return [table for table in _metadata().sorted_tables if include_transient or table.name not in TRANSIENT_TABLES]


def _clean(value):
    """PostgreSQL metinde NUL baytını kabul etmez; PDF'ten gelen metinlerde bulunabilir."""
    return value.replace("\x00", "") if isinstance(value, str) and "\x00" in value else value


def _encode(value):
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    return _clean(value)


def _decode(value, column):
    if isinstance(value, dict) and "$dt" in value:
        return datetime.fromisoformat(value["$dt"])
    if isinstance(value, dict) and "$d" in value:
        return date.fromisoformat(value["$d"])
    if value is not None and isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(value, str) and isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(value, str) and isinstance(column.type, Date):
        return date.fromisoformat(value[:10])
    return value


def read_table(engine: Engine, table) -> list[dict]:
    """Tabloyu modeldeki türlerle okur; modelde olup veritabanında olmayan sütun boş kabul edilir."""
    present = {column["name"] for column in inspect(engine).get_columns(table.name)} if table.name in inspect(engine).get_table_names() else None
    if present is None:
        return []
    columns = [column for column in table.columns if column.name in present]
    order = [column for column in table.primary_key.columns if column.name in present] or columns[:1]
    with engine.connect() as connection:
        rows = connection.execute(select(*columns).order_by(*order)).all()
    return [{column.name: _encode(value) for column, value in zip(columns, row)} for row in rows]


def table_digest(rows: list[dict]) -> str:
    return sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def snapshot(engine: Engine) -> dict:
    tables = {table.name: read_table(engine, table) for table in _tables()}
    return {
        "format": FORMAT, "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": engine.url.get_backend_name(),
        "counts": {name: len(rows) for name, rows in tables.items()},
        "digests": {name: table_digest(rows) for name, rows in tables.items()},
        "tables": tables,
    }


def check(engine: Engine) -> dict:
    """Aktarımdan önce sorun çıkarabilecek durumları raporlar: uzunluk taşmaları ve sahipsiz kayıtlar."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    report = {"backend": engine.url.get_backend_name(), "counts": {}, "overflows": [], "orphans": [], "missing_tables": []}
    with engine.connect() as connection:
        for table in _tables(include_transient=True):
            if table.name not in existing:
                report["missing_tables"].append(table.name)
                continue
            report["counts"][table.name] = connection.execute(select(func.count()).select_from(table)).scalar_one()
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                limit = getattr(column.type, "length", None)
                if not limit or column.name not in present:
                    continue
                longest = connection.execute(select(func.max(func.length(column)))).scalar()
                if longest and longest > limit:
                    report["overflows"].append({"table": table.name, "column": column.name, "limit": limit, "longest": longest})
            for foreign_key in table.foreign_keys:
                parent = foreign_key.column
                if parent.table.name not in existing or foreign_key.parent.name not in present:
                    continue
                orphaned = connection.execute(
                    select(func.count()).select_from(table).where(
                        foreign_key.parent.is_not(None), foreign_key.parent.not_in(select(parent)),
                    )
                ).scalar_one()
                if orphaned:
                    report["orphans"].append({"table": table.name, "column": foreign_key.parent.name, "rows": orphaned})
    report["ok"] = not report["overflows"] and not report["orphans"]
    return report


def _is_empty(engine: Engine) -> bool:
    existing = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        return all(
            connection.execute(select(func.count()).select_from(table)).scalar_one() == 0
            for table in _tables() if table.name in existing
        )


def _complete(row: dict, table) -> dict:
    """Yedekte bulunmayan (sonradan eklenen) sütunları modeldeki sabit varsayılanla doldurur."""
    completed = {}
    for column in table.columns:
        if column.name in row:
            completed[column.name] = row[column.name]
        else:
            default = column.default
            completed[column.name] = default.arg if default is not None and getattr(default, "is_scalar", False) else None
    return completed


def restore(data: dict, target: Engine) -> dict:
    """Yedeği boş hedefe yazar ve doğrular; doğrulama tutmazsa hiçbir şey yazılmamış olur."""
    from .migrate import migrate

    if data.get("format") != FORMAT:
        raise ValueError("Tanınmayan yedek biçimi.")
    migrate(target)
    if not _is_empty(target):
        raise RuntimeError("Hedef veritabanı boş değil. Mevcut verinin üzerine yazılmaz; boş bir veritabanı kullanın.")
    tables = _tables()
    with target.begin() as connection:
        for table in tables:
            rows = data["tables"].get(table.name) or []
            if not rows:
                continue
            columns = {column.name: column for column in table.columns}
            payload = [{name: _decode(value, columns[name]) for name, value in _complete(row, table).items()} for row in rows]
            for start in range(0, len(payload), 500):
                connection.execute(table.insert(), payload[start:start + 500])
        if target.dialect.name == "postgresql":
            # Kimlikler kaynaktaki değerleriyle yazıldı; sıra sayaçları en büyük kimliğe ayarlanır.
            for table in tables:
                for column in table.primary_key.columns:
                    if column.autoincrement is not False and str(column.type.python_type) == "<class 'int'>" and len(table.primary_key.columns) == 1:
                        connection.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', '{column.name}'), "
                            f"COALESCE((SELECT MAX(\"{column.name}\") FROM \"{table.name}\"), 1), "
                            f"(SELECT COUNT(*) FROM \"{table.name}\") > 0) "
                            f"WHERE pg_get_serial_sequence('\"{table.name}\"', '{column.name}') IS NOT NULL"
                        ))
        # Aynı işlem içinde geri okuyup karşılaştır: fark varsa istisna işlemi geri alır.
        mismatches = []
        for table in tables:
            written = connection.execute(select(*table.columns).order_by(*table.primary_key.columns)).all()
            rows = [{column.name: _encode(value) for column, value in zip(table.columns, row)} for row in written]
            expected = data["tables"].get(table.name) or []
            expected = [_complete(row, table) for row in expected]
            if len(rows) != len(expected):
                mismatches.append(f"{table.name}: {len(expected)} satır beklenirken {len(rows)} yazıldı")
            elif table_digest(rows) != table_digest(expected):
                mismatches.append(f"{table.name}: içerik özeti farklı")
        if mismatches:
            raise RuntimeError("Aktarım doğrulaması başarısız, hiçbir şey yazılmadı: " + "; ".join(mismatches))
    return {"tables": len(tables), "rows": sum(len(rows) for rows in data["tables"].values()), "counts": data["counts"]}


def copy(source: Engine, target: Engine) -> dict:
    problems = check(source)
    if problems["orphans"]:
        raise RuntimeError(f"Kaynakta sahipsiz kayıtlar var; önce incelenmeli: {problems['orphans']}")
    if problems["overflows"] and target.dialect.name == "postgresql":
        raise RuntimeError(f"Kaynakta sütun sınırını aşan değerler var: {problems['overflows']}")
    return restore(snapshot(source), target)


def write_backup(engine: Engine, path: str) -> dict:
    data = snapshot(engine)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    return {"path": path, "counts": data["counts"]}


def read_backup(path: str) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def seed_empty_database(target: Engine, seed_path) -> dict | None:
    """Boş üretim veritabanını depodaki son SQLite dosyasından bir kez doldurur (doğrulamalı)."""
    from pathlib import Path

    from .database import make_engine
    from .migrate import migrate

    seed_path = Path(seed_path)
    if not seed_path.is_file():
        return None
    migrate(target)
    if not _is_empty(target):
        return None
    source = make_engine(f"sqlite:///{seed_path}")
    try:
        # Kaynak dosyaya dokunulmaz: eksik sütunlar okuma sırasında boş kabul edilir.
        return restore(snapshot(source), target)
    finally:
        source.dispose()


def main(argv: list[str] | None = None) -> int:
    from .database import DATABASE_URL, make_engine

    parser = argparse.ArgumentParser(description="CareerPilot veritabanı araçları")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "backup"):
        command = commands.add_parser(name)
        command.add_argument("--url", default=DATABASE_URL)
        if name == "backup":
            command.add_argument("--out", required=True)
    command = commands.add_parser("restore")
    command.add_argument("--in", dest="source", required=True)
    command.add_argument("--url", required=True)
    command = commands.add_parser("copy")
    command.add_argument("--from", dest="source", required=True)
    command.add_argument("--to", dest="target", required=True)
    args = parser.parse_args(argv)

    if args.command == "check":
        outcome = check(make_engine(args.url))
    elif args.command == "backup":
        outcome = write_backup(make_engine(args.url), args.out)
    elif args.command == "restore":
        outcome = restore(read_backup(args.source), make_engine(args.url))
    else:
        outcome = copy(make_engine(args.source), make_engine(args.target))
    print(json.dumps(outcome, ensure_ascii=False, indent=2, default=str))
    return 0 if outcome.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
