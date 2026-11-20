"""Yeni eşleşme ve son başvuru hatırlatma bildirimleri."""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
import json
import logging
import os
import smtplib

import requests
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import config
from .matching import build_matches, job_summaries
from .models import AppSetting, Notification
from .schemas import NotificationSettings

logger = logging.getLogger(__name__)
SETTINGS_KEY = "notifications"
CATEGORY_LABELS = {"UYGUN": "Uygun ilan", "POTANSİYEL OLARAK UYGUN": "Doğrulanmalı"}


def load_settings(db: Session) -> NotificationSettings:
    settings = NotificationSettings()
    row = db.get(AppSetting, SETTINGS_KEY)
    if row and row.value:
        try:
            settings = NotificationSettings(**json.loads(row.value))
        except (ValueError, TypeError):
            logger.warning("Stored notification settings are invalid; using defaults")
    # Zamanlanmış (arayüzsüz) çalıştırmalarda alıcılar ortam değişkeninden verilebilir;
    # böylece e-posta adresi ya da sohbet kimliği veritabanına ve depoya yazılmaz.
    email_to = os.getenv("CAREERPILOT_NOTIFY_EMAIL_TO", "").strip()
    chat_id = os.getenv("CAREERPILOT_NOTIFY_TELEGRAM_CHAT_ID", "").strip()
    updates = {}
    if email_to:
        updates.update(email_enabled=True, email_to=email_to)
    if chat_id:
        updates.update(telegram_enabled=True, telegram_chat_id=chat_id)
    return settings.model_copy(update=updates) if updates else settings


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
            and summary["tracking"] not in ("applied", "awaiting", "won", "lost")
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
    if config.env_flag("CAREERPILOT_NOTIFY_DISABLED"):
        return {"skipped": "gönderim kapalı (deneme çalıştırması)"}
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
    if "skipped" not in results and all(value == "ok" for value in results.values()):
        now = datetime.now()
        for item in pending:
            item.delivered_at = now
        db.commit()
    return {"pending": len(pending), "channels": results}


def refresh_daily(db: Session, today=None) -> int:
    """Site açıldığında hesaplanan günlük bildirimler ve yaklaşan olay hatırlatmaları.
    Her ilan olayı/tarihi için yinelenen bildirim oluşturulmaz."""
    from datetime import date as date_type, timedelta

    from .events import EVENT_LABELS, task_occurrences
    from .models import Job, JobEvent, UserTask

    today = today or date_type.today()
    tomorrow = today + timedelta(days=1)
    reminder_days = load_settings(db).deadline_reminder_days
    reminder_end = today + timedelta(days=reminder_days)
    summaries = {item["job_id"]: item for item in job_summaries(build_matches(db, full=False, today=today))}
    existing = set(db.scalars(select(Notification.dedupe_key)).all())
    created = 0

    def add(kind: str, key: str, job_id, category: str, title: str, body: str) -> None:
        nonlocal created
        if key in existing:
            return
        existing.add(key)
        db.add(Notification(kind=kind, dedupe_key=key, job_id=job_id, category=category, title=title[:400], body=body,
                            created_at=datetime.now(), delivered_at=datetime.now()))
        created += 1

    def relevant(summary) -> bool:
        if summary is None or summary["tracking"] == "hidden" or summary["application_status"] == "İptal Edildi":
            return False
        # Elle "uygun değil" denilen ilanın hatırlatmaları kapalıdır.
        return summary["category"] != "UYGUN DEĞİL" or summary["tracking"] in ("saved", "applied", "awaiting")

    events = db.scalars(select(JobEvent).where(
        JobEvent.deleted.is_(False), JobEvent.event_date >= today, JobEvent.event_date <= max(tomorrow, reminder_end),
    )).all()
    for event in events:
        summary = summaries.get(event.job_id)
        if not relevant(summary):
            continue
        applied = summary["tracking"] in ("applied", "awaiting", "won", "lost")
        label = event.title or EVENT_LABELS.get(event.kind, "Olay")
        name = f"{summary['organization']} — {summary['title']}"
        if event.kind == "application_deadline":
            if event.event_date > tomorrow:
                continue  # Son başvuru hatırlatmaları tercih edilen gün sayısına göre üretilir.
            if applied:
                continue
            when = "Bugün son gün" if event.event_date == today else "Yarın son gün"
            add("deadline", f"day:{event.id}:{event.event_date}:{when}", event.job_id, summary["category"], f"{when}: {summary['organization']}", name)
        elif event.event_date == today:
            add("event", f"day:{event.id}:{event.event_date}", event.job_id, summary["category"], f"Bugün: {label} — {summary['organization']}",
                name + (f" ({event.url})" if event.url else ""))
        elif reminder_days and event.kind in ("application_start", "exam", "interview", "result", "documents", "appointment"):
            days_left = (event.event_date - today).days
            add("event_upcoming", f"event:{event.id}:{event.event_date}", event.job_id, summary["category"],
                f"Yaklaşan etkinlik ({days_left} gün): {label} — {summary['organization']}",
                name + (f" · {event.url}" if event.url else ""))

    for event in db.scalars(select(JobEvent).where(JobEvent.previous_date.is_not(None), JobEvent.deleted.is_(False))).all():
        summary = summaries.get(event.job_id)
        if relevant(summary):
            add("date_change", f"datechange:{event.id}:{event.event_date}", event.job_id, summary["category"],
                f"Tarih değişti: {summary['organization']}",
                f"{EVENT_LABELS.get(event.kind, 'Olay')}: {event.previous_date:%d.%m.%Y} → {event.event_date:%d.%m.%Y}")

    for summary in summaries.values():
        if summary.get("stale"):
            add("verification_stale", f"stale:{summary['job_id']}:{'|'.join(summary['stale_changes'])[:80]}", summary["job_id"], summary["category"],
                f"İlan güncellendi, doğrulamanı gözden geçir: {summary['organization']}",
                "Değişen: " + ", ".join(summary["stale_changes"]) + ". Kararınız korunuyor.")

    todays_tasks = db.scalars(select(UserTask).where(
        UserTask.task_date <= today,
        ((UserTask.recurrence == "none") & (UserTask.task_date >= today))
        | ((UserTask.recurrence != "none") & (or_(UserTask.until.is_(None), UserTask.until >= today))),
    )).all()
    todays = [item for item in task_occurrences(todays_tasks, today, today) if not item["done"]]
    if todays:
        add("tasks", f"tasks:{today}", None, "", f"Bugünkü görevlerin ({len(todays)})", ", ".join(item["title"] for item in todays[:8]))

    if created:
        db.commit()
    return created


def process_notifications(db: Session) -> dict:
    settings = load_settings(db)
    created = generate_notifications(db, settings=settings)
    delivery = deliver_pending(db, settings)
    return {"created": len(created), **delivery}
