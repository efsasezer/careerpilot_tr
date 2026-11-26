"""Tek şifreli giriş ve sunucu tarafında tutulan oturumlar.

- Şifre ve oturum imzalama anahtarı yalnızca ortam değişkenlerinden okunur.
- Tarayıcıya yalnızca HttpOnly çerez verilir; çerezdeki değer sunucudaki oturum kaydının
  imzalı kimliğidir. Çıkış, kaydı silerek oturumu sunucuda geçersiz kılar.
"""

from __future__ import annotations

from . import clock
from datetime import datetime, timedelta
import hashlib
import hmac
import os
import secrets
import threading
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import UserSession

COOKIE_NAME = "careerpilot_session"
SESSION_DAYS = 14
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 10 * 60
LOCKOUT_SECONDS = 15 * 60


class AuthConfigError(RuntimeError):
    pass


def configured_password() -> str:
    return os.getenv("CAREERPILOT_PASSWORD", "")


def session_secret() -> str:
    return os.getenv("CAREERPILOT_SESSION_SECRET", "")


def config_error() -> str | None:
    missing = [
        name for name, value in (
            ("CAREERPILOT_PASSWORD", configured_password()),
            ("CAREERPILOT_SESSION_SECRET", session_secret()),
        ) if not value.strip()
    ]
    if missing:
        return "Sunucuda giriş ayarı eksik: " + ", ".join(missing) + " ortam değişkeni tanımlanmalı."
    if len(session_secret().strip()) < 16:
        return "CAREERPILOT_SESSION_SECRET en az 16 karakter olmalı."
    return None


def password_matches(candidate: str) -> bool:
    expected = configured_password()
    if not expected:
        return False
    # Uzunluk farkı da sabit zamanda karşılaştırılsın diye özetler karşılaştırılır.
    return hmac.compare_digest(
        hashlib.sha256(candidate.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def _sign(session_id: str) -> str:
    return hmac.new(session_secret().encode("utf-8"), session_id.encode("ascii"), hashlib.sha256).hexdigest()


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def create_session(db: Session) -> str:
    """Yeni oturum açar ve çereze yazılacak imzalı değeri döndürür."""
    session_id = secrets.token_urlsafe(32)
    now = clock.now()
    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    db.add(UserSession(token_hash=_hash(session_id), created_at=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    db.commit()
    return f"{session_id}.{_sign(session_id)}"


def _session_id(cookie_value: str | None) -> str | None:
    if not cookie_value or "." not in cookie_value or not session_secret():
        return None
    session_id, signature = cookie_value.rsplit(".", 1)
    try:
        expected = _sign(session_id)
    except UnicodeEncodeError:
        return None
    return session_id if hmac.compare_digest(signature, expected) else None


def is_authenticated(db: Session, cookie_value: str | None) -> bool:
    session_id = _session_id(cookie_value)
    if session_id is None:
        return False
    record = db.get(UserSession, _hash(session_id))
    return record is not None and record.expires_at > clock.now()


def destroy_session(db: Session, cookie_value: str | None) -> None:
    session_id = _session_id(cookie_value)
    if session_id is not None:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash(session_id)))
        db.commit()


def active_session_count(db: Session) -> int:
    return len(db.scalars(select(UserSession.token_hash).where(UserSession.expires_at > clock.now())).all())


class LoginLimiter:
    """Aynı adresten kısa sürede çok sayıda yanlış denemeyi geçici olarak engeller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, client: str) -> int:
        with self._lock:
            remaining = self._locked_until.get(client, 0) - time.monotonic()
            return max(0, int(remaining) + 1) if remaining > 0 else 0

    def record_failure(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [stamp for stamp in self._failures.get(client, []) if now - stamp < FAILURE_WINDOW_SECONDS]
            recent.append(now)
            self._failures[client] = recent
            if len(recent) >= MAX_FAILURES:
                self._locked_until[client] = now + LOCKOUT_SECONDS
                self._failures[client] = []

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
            self._locked_until.pop(client, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


login_limiter = LoginLimiter()
