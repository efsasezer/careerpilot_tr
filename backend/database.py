from pathlib import Path
import os
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'careerpilot.db'}"


def normalize_database_url(value: str) -> str:
    """Barındırma hizmetlerinin verdiği `postgres://` adresini SQLAlchemy'nin sürücü adına çevirir."""
    value = (value or "").strip()
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "")) or DEFAULT_DATABASE_URL
IS_SQLITE = DATABASE_URL.startswith("sqlite")


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

    seed = BASE_DIR / "careerpilot.db"
    seeding = os.getenv("CAREERPILOT_DB_SEED_FROM_REPO", "").strip().casefold() in {"1", "true", "yes", "on"}
    if seeding and not database_path.is_file() and seed.is_file() and database_path.resolve() != seed.resolve():
        # Kalıcı diskteki veritabanı ilk açılışta depodaki ilan verisiyle başlatılır.
        import shutil

        database_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed, database_path)
        return
    if not database_path.is_file():
        if os.getenv("CAREERPILOT_DB_AUTOCREATE", "").strip().casefold() in {"1", "true", "yes", "on"}:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            return
        raise FileNotFoundError(
            f"SQLite veritabanı bulunamadı: {database_path.resolve()}. "
            "careerpilot.db dosyasını proje köküne yerleştirin veya boş bir veritabanıyla başlamak için "
            "CAREERPILOT_DB_AUTOCREATE=true ayarlayın."
        )


ensure_sqlite_database_file_exists(DATABASE_URL)


def make_engine(url: str):
    """SQLite ve PostgreSQL için aynı ayarlarla motor kurar."""
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        created = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)

        @event.listens_for(created, "connect")
        def _sqlite_pragmas(connection, _record):  # pragma: no cover - sürücü geri çağrısı
            cursor = connection.cursor()
            # Tarama yazarken arayüzün okuyabilmesi için WAL; kilitte hata yerine kısa bekleme.
            cursor.execute("PRAGMA busy_timeout=30000")
            if ":memory:" not in url and "mode=memory" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return created
    # Barındırılan PostgreSQL boşta kalan bağlantıları kapatır: kullanmadan önce yokla, 5 dk'da yenile.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5, future=True)


def storage_status() -> dict:
    """Verinin kalıcı olup olmadığını söyler; kalıcı değilse arayüz bunu açıkça gösterir."""
    if not IS_SQLITE:
        return {"backend": "postgresql", "durable": True, "warning": None}
    hosted = bool(os.getenv("RENDER"))
    on_disk = "/var/data" in DATABASE_URL or bool(os.getenv("CAREERPILOT_PERSISTENT_DISK"))
    if hosted and not on_disk:
        return {
            "backend": "sqlite", "durable": False,
            "warning": "Veriler kalıcı değil: bu sunucudaki dosya sistemi her yeniden başlatmada sıfırlanır. "
                       "Profil, kayıtlar ve notlar kaybolabilir. Kalıcı PostgreSQL için DATABASE_URL tanımlanmalı.",
        }
    return {"backend": "sqlite", "durable": True, "warning": None}


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
