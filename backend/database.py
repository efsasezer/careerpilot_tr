from pathlib import Path
import os
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'careerpilot.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def ensure_sqlite_database_file_exists(database_url: str) -> None:
    url = make_url(database_url)
    database = url.database
    if (
        url.get_backend_name() != "sqlite"
        or not database
        or database == ":memory:"
        or database == "file::memory:"
        or url.query.get("mode") == "memory"
    ):
        return

    if database.startswith("file:"):
        uri_value = database[5:]
        if os.name == "nt" and len(uri_value) > 2 and uri_value[1] == ":":
            uri_path = unquote(uri_value)
        else:
            uri = urlsplit(uri_value)
            uri_path = unquote(uri.path)
            if uri.netloc:
                uri_path = f"//{uri.netloc}{uri_path}"
            if os.name == "nt" and len(uri_path) > 2 and uri_path[0] == "/" and uri_path[2] == ":":
                uri_path = uri_path[1:]
        database_path = Path(uri_path)
    else:
        database_path = Path(database)

    if not database_path.is_file():
        raise FileNotFoundError(
            f"SQLite veritabanı bulunamadı: {database_path.resolve()}. "
            "careerpilot.db dosyasını proje köküne yerleştirin; boş veritabanı oluşturulmadı."
        )


ensure_sqlite_database_file_exists(DATABASE_URL)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
