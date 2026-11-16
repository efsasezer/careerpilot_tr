"""Ortam değişkenlerinden okunan çalışma ayarları."""

from __future__ import annotations

import os

APP_VERSION = "1.0.0"
_TRUE = {"1", "true", "yes", "on"}


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in _TRUE


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def sync_interval_hours() -> float:
    """Sunucu içi otomatik tarama aralığı. Varsayılan 0: kapalı (tarama elle ya da GitHub Actions ile)."""
    return max(0.0, env_float("CAREERPILOT_SYNC_INTERVAL_HOURS", 0.0))


def source_request_delay() -> float:
    return max(0.0, env_float("CAREERPILOT_SOURCE_REQUEST_DELAY_SECONDS", 0.75))


def public_app_url() -> str:
    return os.getenv("CAREERPILOT_APP_URL", "http://localhost:5173").strip().rstrip("/")


def smtp_settings() -> dict | None:
    host = os.getenv("CAREERPILOT_SMTP_HOST", "").strip()
    if not host:
        return None
    user = os.getenv("CAREERPILOT_SMTP_USER", "").strip()
    return {
        "host": host,
        "port": int(env_float("CAREERPILOT_SMTP_PORT", 587)),
        "user": user,
        "password": os.getenv("CAREERPILOT_SMTP_PASSWORD", ""),
        "sender": os.getenv("CAREERPILOT_SMTP_FROM", "").strip() or user,
        "starttls": not env_flag("CAREERPILOT_SMTP_NO_TLS"),
    }


def telegram_bot_token() -> str:
    return os.getenv("CAREERPILOT_TELEGRAM_BOT_TOKEN", "").strip()
