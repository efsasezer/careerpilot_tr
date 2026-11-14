"""Reconcile existing SBB rows from the official listing index without deleting rows."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .eligibility import normalize_text
from .database import SessionLocal
from .models import Job
from .sources.sbb import SBBSource, parse_sbb_listing_label


def _label_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value or "")).strip()


def _url_key(value: str) -> str:
    parts = urlsplit((value or "").strip())
    return urlunsplit((
        parts.scheme.casefold(),
        parts.netloc.casefold(),
        unquote(parts.path).rstrip("/"),
        unquote(parts.query),
        "",
    ))


def backfill_existing_sbb_jobs(
    db: Session,
    listings: list[dict],
    *,
    apply: bool = False,
    current_date: date | None = None,
) -> dict[str, int]:
    """Update only pre-existing SBB jobs; unmatched rows use their stored official label."""
    current_date = current_date or date.today()
    existing = list(db.scalars(
        select(Job)
        .where(Job.sector == "public", Job.source_name == SBBSource.source_name)
        .order_by(Job.id)
    ).all())
    live_by_label = {
        _label_key(str(item.get("listing_text") or "")): item
        for item in listings
    }
    live_by_url = {
        _url_key(str(item.get("detail_url") or "")): item
        for item in listings
    }
    live_by_org_title = {
        _label_key(f"{item.get('institution', '')} {item.get('title', '')}"): item
        for item in listings
    }
    report = {
        "existing": len(existing),
        "matched_live": 0,
        "matched_snapshot": 0,
        "updated": 0,
        "unparseable": 0,
    }

    fields = (
        "title",
        "organization",
        "city",
        "source_url",
        "source_name",
        "description",
        "application_start",
        "application_deadline",
        "announcement_date",
        "quota",
        "employment_type",
        "recruitment_method",
        "education_requirement",
        "qualification_codes",
        "kpss_score_type",
        "kpss_min_score",
    )
    for job in existing:
        item = (
            live_by_url.get(_url_key(job.source_url))
            or live_by_label.get(_label_key(job.title))
            or live_by_org_title.get(_label_key(f"{job.organization} {job.title}"))
        )
        if item is not None:
            report["matched_live"] += 1
            values = {
                "title": item["title"],
                "organization": item["institution"],
                "city": item.get("city") or "",
                "source_url": item.get("source_url") or SBBSource.base_url,
                "source_name": SBBSource.source_name,
                "description": job.description or item.get("description_html") or item["listing_text"],
                "application_start": item.get("application_start_date"),
                "application_deadline": item.get("application_end_date"),
                "announcement_date": item.get("announcement_date"),
                "quota": item.get("quota") or "",
                "employment_type": item.get("employment_type") or "Kaynakta belirtilmedi",
                "recruitment_method": item.get("recruitment_method") or "Kaynakta belirtilmedi",
                "education_requirement": item.get("education_requirement") or "",
                "qualification_codes": item.get("qualification_codes") or "",
                "kpss_score_type": item.get("kpss_score_type") or "",
                "kpss_min_score": item.get("kpss_min_score"),
            }
        else:
            report["matched_snapshot"] += 1
            historical_label = job.description or job.title
            parsed = parse_sbb_listing_label(
                historical_label,
                source_url=job.source_url,
                current_date=current_date,
            )
            if parsed["institution"] == "Kaynakta bulunamadı":
                parsed = parse_sbb_listing_label(
                    job.title,
                    source_url=job.source_url,
                    current_date=current_date,
                )
            if parsed["institution"] == "Kaynakta bulunamadı":
                report["unparseable"] += 1
                continue
            values = {
                "title": parsed["title"],
                "organization": parsed["institution"],
                "city": "",
                "source_url": SBBSource.base_url,
                "source_name": SBBSource.source_name,
                "description": job.description or job.title,
                "application_start": parsed["application_start_date"],
                "application_deadline": parsed["application_end_date"],
                "announcement_date": None,
                "quota": parsed["quota"] or "",
                "employment_type": parsed["employment_type"],
                "recruitment_method": parsed["recruitment_method"],
                "education_requirement": "",
                "qualification_codes": "",
                "kpss_score_type": "",
                "kpss_min_score": None,
            }

        changed = False
        for field in fields:
            if getattr(job, field) != values[field]:
                setattr(job, field, values[field])
                changed = True
        if changed:
            job.updated_at = datetime.now()
            report["updated"] += 1

    if apply:
        db.commit()
    else:
        db.rollback()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates to existing SBB records. By default, only report a dry run.",
    )
    args = parser.parse_args()

    listings = SBBSource().fetch_listings()
    with SessionLocal() as db:
        report = backfill_existing_sbb_jobs(db, listings, apply=args.apply)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    for key, value in report.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
