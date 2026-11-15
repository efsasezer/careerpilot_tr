"""Yeni eşleşme ve son başvuru hatırlatma bildirimleri."""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
import json
import logging
import smtplib

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .matching import build_matches, job_summaries
from .models import AppSetting, Notification
from .schemas import NotificationSettings

logger = logging.getLogger(__name__)
SETTINGS_KEY = "notifications"
CATEGORY_LABELS = {"UYGUN": "Uygun ilan", "POTANSİYEL OLARAK UYGUN": "Doğrulanmalı"}


def load_settings(db: Session) -> NotificationSettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row and row.value:
        try:
            return NotificationSettings(**json.loads(row.value))
        except (ValueError, TypeError):
            logger.warning("Stored notification settings are invalid; using defaults")
    return NotificationSettings()


def save_settings(db: Session, settings: NotificationSettings) -> NotificationSettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY)
        db.add(row)
    row.value = settings.model_dump_json()
    db.commit()
    return settings


def channel_status() -> dict:
    return {
        "email_available": config.smtp_settings() is not None,
        "telegram_available": bool(config.telegram_bot_token()),
    }


def _format_deadline(value: str | None) -> str:
    if not value:
        return "son başvuru tarihi belirtilmemiş"
    year, month, day = value.split("-")
    return f"son başvuru {day}.{month}.{year}"


def generate_notifications(db: Session, matches: dict | None = None, settings: NotificationSettings | None = None) -> list[Notification]:
    """Henüz bildirilmemiş yeni eşleşmeler ve yaklaşan son başvurular için kayıt oluşturur."""
    settings = settings or load_settings(db)
    matches = matches or build_matches(db, full=False)
    existing = set(db.scalars(select(Notification.dedupe_key)).all())
    created: list[Notification] = []

    def add(kind: str, key: str, summary: dict, title: str, body: str) -> None:
        if key in existing:
            return
        existing.add(key)
        record = Notification(
            kind=kind, dedupe_key=key, job_id=summary["job_id"], category=summary["category"],
            title=title[:400], body=body, created_at=datetime.now(),
        )
        db.add(record)
        created.append(record)

    for summary in job_summaries(matches):
        if summary["tracking"] == "hidden" or summary["application_status"] in ("Başvuru Sona Erdi", "İptal Edildi"):
            continue
        category = summary["category"]
        if category not in settings.notify_categories:
            continue
        if summary["data_quality"] == "listing_only" and category != "UYGUN":
            continue  # ayrıntısı okunamayan ilanlar için "potansiyel" bildirimi gürültü olur
        if settings.only_preferred_locations and summary["location_match"] is False:
            continue
        if summary["kind"] == "academic" and not summary["education_met"]:
            continue  # akademik ilan yalnızca adayın bölümü açıkça aranıyorsa bildirilir

        positions = [
            name for name in dict.fromkeys(summary["positions"])
            if name and name not in summary["title"]
        ]
        position_text = ""
        if positions:
            position_text = " Pozisyonlar: " + ", ".join(positions[:4]) + (f" ve {len(positions) - 4} diğer." if len(positions) > 4 else ".")
        label = CATEGORY_LABELS[category]
        add(
            "new_match",
            f"match:{summary['job_id']}:{category}",
            summary,
            f"{label}: {summary['organization']}",
            f"{summary['title']} — {_format_deadline(summary['application_deadline'])}.{position_text}",
        )

        days_left = summary["days_left"]
        if (
            settings.deadline_reminder_days
            and summary["application_status"] == "Başvuru Açık"
            and summary["tracking"] != "applied"
            and days_left is not None
            and 0 <= days_left <= settings.deadline_reminder_days
        ):
            when = "bugün son gün" if days_left == 0 else f"son {days_left} gün"
            add(
                "deadline",
                f"deadline:{summary['job_id']}:{summary['application_deadline']}",
                summary,
                f"Son başvuru yaklaşıyor ({when}): {summary['organization']}",
                f"{summary['title']} — {_format_deadline(summary['application_deadline'])}.",
            )

    if created:
        db.commit()
    return created


def _digest(notifications: list[Notification]) -> tuple[str, str]:
    matches = [item for item in notifications if item.kind == "new_match"]
    deadlines = [item for item in notifications if item.kind == "deadline"]
    parts = []
    if matches:
        parts.append(f"{len(matches)} yeni uygun ilan")
    if deadlines:
        parts.append(f"{len(deadlines)} yaklaşan son başvuru")
    subject = "CareerPilot TR: " + " ve ".join(parts)
    lines = []
    for heading, group in (("Yeni eşleşen ilanlar", matches), ("Son başvurusu yaklaşanlar", deadlines)):
        if not group:
            continue
        lines.append(heading + ":")
        for item in group[:15]:
            lines.append(f"• {item.title}\n  {item.body}")
        if len(group) > 15:
            lines.append(f"… ve {len(group) - 15} ilan daha.")
        lines.append("")
    lines.append(f"Tümünü görmek için: {config.public_app_url()}/")
    lines.append("Bu sonuçlar ön elemedir; başvurudan önce resmî ilanı kontrol edin.")
    return subject, "\n".join(lines)


def send_email(to: str, subject: str, body: str) -> None:
    smtp = config.smtp_settings()
    if smtp is None:
        raise RuntimeError("Sunucuda SMTP ayarları tanımlı değil (CAREERPILOT_SMTP_HOST).")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp["sender"]
    message["To"] = to
    message.set_content(body)
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=20) as client:
        if smtp["starttls"]:
            client.starttls()
        if smtp["user"]:
            client.login(smtp["user"], smtp["password"])
        client.send_message(message)


def send_telegram(chat_id: str, text: str) -> None:
    token = config.telegram_bot_token()
    if not token:
        raise RuntimeError("Sunucuda Telegram bot anahtarı tanımlı değil (CAREERPILOT_TELEGRAM_BOT_TOKEN).")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram mesajı gönderilemedi (HTTP {response.status_code}).")


def send_to_channels(settings: NotificationSettings, subject: str, body: str) -> dict:
    """Etkin kanallara gönderir; kanal başına sonucu döndürür."""
    results = {}
    if settings.email_enabled and settings.email_to:
        try:
            send_email(settings.email_to, subject, body)
            results["email"] = "ok"
        except Exception as error:
            results["email"] = f"hata: {error}"
    if settings.telegram_enabled and settings.telegram_chat_id:
        try:
            send_telegram(settings.telegram_chat_id, f"{subject}\n\n{body}")
            results["telegram"] = "ok"
        except Exception as error:
            results["telegram"] = f"hata: {error}"
    return results


def deliver_pending(db: Session, settings: NotificationSettings | None = None) -> dict:
    settings = settings or load_settings(db)
    pending = list(db.scalars(
        select(Notification).where(Notification.delivered_at.is_(None)).order_by(Notification.id)
    ).all())
    if not pending:
        return {"pending": 0, "channels": {}}
    subject, body = _digest(pending)
    results = send_to_channels(settings, subject, body)
    # Bir kanal hata verdiyse sonraki taramada yeniden denenir.
    if all(value == "ok" for value in results.values()):
        now = datetime.now()
        for item in pending:
            item.delivered_at = now
        db.commit()
    return {"pending": len(pending), "channels": results}


def process_notifications(db: Session) -> dict:
    settings = load_settings(db)
    created = generate_notifications(db, settings=settings)
    delivery = deliver_pending(db, settings)
    return {"created": len(created), **delivery}
