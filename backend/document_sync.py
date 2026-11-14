from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import logging
import re
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .documents import (
    DocumentFetchError,
    DocumentParseError,
    discover_document_links,
    filter_document_links,
    fetch_url,
    parse_document,
)
from .kariyerkapisi import scrape_public_listing_details
from .migrate import migrate as run_migrations
from .models import DocumentPosition, Job, JobDocument, JobDocumentScan


logger = logging.getLogger(__name__)
DIRECT_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".rtf", ".html", ".htm", ".aspx"}


def _is_direct_document(url: str) -> bool:
    path = unquote(urlsplit(url).path).casefold()
    return any(path.endswith(extension) for extension in DIRECT_DOCUMENT_EXTENSIONS)


def _scan_record(db: Session, job_id: int) -> JobDocumentScan:
    record = db.scalar(select(JobDocumentScan).where(JobDocumentScan.job_id == job_id))
    if record is None:
        record = JobDocumentScan(job_id=job_id)
        db.add(record)
        db.flush()
    return record


def _fetch_job_page(job: Job, browser_outcome: dict | None) -> tuple[list[dict[str, str]], str | None]:
    url = (job.source_url or "").strip()
    if not url:
        raise DocumentFetchError("İlanın resmî kaynak bağlantısı bulunmuyor.")
    if _is_direct_document(url):
        return [{"url": url, "title": job.title or "Resmî ilan belgesi"}], None

    parsed = urlsplit(url)
    if (
        "sbb" in (job.source_name or "").casefold()
        and parsed.path.rstrip("/") in {"", "/"}
    ):
        raise DocumentFetchError(
            "Bu SBB kaydında ilan detay bağlantısı değil ana liste adresi saklı; ek belge ilanla güvenle eşleştirilemiyor."
        )

    if "kariyer kapısı" in (job.source_name or "").casefold():
        if not browser_outcome:
            raise DocumentFetchError("Kariyer Kapısı ilan detay sayfası taranamadı.")
        if browser_outcome.get("error"):
            raise DocumentFetchError(str(browser_outcome["error"]))
        details = browser_outcome.get("details") or {}
        return filter_document_links(details.get("attachments") or []), None

    page_response = fetch_url(url, max_bytes=5 * 1024 * 1024)
    if page_response["not_modified"]:
        raise DocumentFetchError("İlan sayfası beklenmedik biçimde 304 yanıtı verdi.")
    content_type = page_response["content_type"].casefold()
    if "html" not in content_type and not urlsplit(page_response["url"]).path.casefold().endswith((".htm", ".html", ".aspx")):
        raise DocumentFetchError(
            f"İlan bağlantısı HTML detay sayfası değil (Content-Type: {content_type or 'belirtilmedi'})."
        )
    html = page_response["body"].decode("utf-8", errors="replace")
    links = discover_document_links(page_response["url"], html)
    return links, None


def _save_document_positions(
    db: Session,
    document: JobDocument,
    positions: list[dict],
) -> None:
    db.execute(delete(DocumentPosition).where(DocumentPosition.document_id == document.id))
    for fallback_index, item in enumerate(positions):
        db.add(DocumentPosition(
            document_id=document.id,
            row_index=int(item.get("row_index", fallback_index)),
            position_title=str(item.get("position_title") or "")[:250],
            education_requirement=str(item.get("education_requirement") or ""),
            quota=str(item.get("quota") or "")[:100],
            kpss_score_type=str(item.get("kpss_score_type") or "")[:50],
            kpss_min_score=item.get("kpss_min_score"),
            city=str(item.get("city") or "")[:500],
            qualification_codes=str(item.get("qualification_codes") or "")[:500],
            written_exam_invite_text=str(item.get("written_exam_invite_text") or ""),
            written_exam_invite_count=item.get("written_exam_invite_count"),
            requirements_text=str(item.get("requirements_text") or ""),
            raw_cells=json.dumps(item.get("raw_cells") or {}, ensure_ascii=False),
        ))


def _sync_document(
    db: Session,
    job: Job,
    link: dict[str, str],
    visited: set[str],
    report: dict,
    depth: int = 0,
) -> None:
    url = str(link.get("url") or "").strip()
    if not url or url in visited or depth > 2:
        return
    visited.add(url)

    document = db.scalar(select(JobDocument).where(
        JobDocument.job_id == job.id,
        JobDocument.document_url == url,
    ))
    if document is None:
        document = JobDocument(
            job_id=job.id,
            document_url=url,
            title=str(link.get("title") or "")[:500],
            status="discovered",
        )
        db.add(document)
        db.flush()
    elif link.get("title"):
        document.title = str(link["title"])[:500]

    try:
        response = fetch_url(
            url,
            etag=document.etag or None,
            last_modified=document.last_modified or None,
        )
        if response["not_modified"]:
            document.checked_at = datetime.now()
            if document.parsed_content_hash:
                document.status = "partially_read" if document.error else "read"
            report["unchanged"] += 1
            return

        body = response["body"]
        current_hash = sha256(body).hexdigest()
        document.content_type = str(response["content_type"] or "")[:200]
        document.etag = str(response["etag"] or "")[:500]
        document.last_modified = str(response["last_modified"] or "")[:200]
        document.checked_at = datetime.now()
        document.content_hash = current_hash
        if current_hash == document.content_hash and document.parsed_content_hash == current_hash:
            document.status = "read"
            document.error = ""
            report["unchanged"] += 1
            return

        parsed = parse_document(url, body, response["content_type"])
        document.parsed_content_hash = current_hash
        document.extracted_text = parsed["text"]
        document.shared_requirements = parsed.get("shared_requirements") or ""
        document.status = "partially_read" if parsed.get("partially_read") else "read"
        document.error = (
            "Belgenin metninde çözümlenemeyen karakterler var."
            if parsed.get("partially_read") else ""
        )
        _save_document_positions(db, document, parsed["positions"])
        db.flush()
        report["read"] += 1
        report["positions"] += len(parsed["positions"])
        for child_link in parsed.get("links") or []:
            _sync_document(db, job, child_link, visited, report, depth + 1)
    except DocumentParseError as error:
        document.status = "unreadable"
        document.error = str(error)
        document.checked_at = datetime.now()
        report["errors"] += 1
        report["details"].append({"job_id": job.id, "url": url, "error": str(error)})
        logger.warning("Official attachment could not be parsed for job %s: %s", job.id, error)
    except DocumentFetchError as error:
        document.status = "unavailable"
        document.error = str(error)
        document.checked_at = datetime.now()
        report["errors"] += 1
        report["details"].append({"job_id": job.id, "url": url, "error": str(error)})
        logger.warning("Official attachment could not be fetched for job %s: %s", job.id, error)


def sync_job_documents(
    db: Session,
    job: Job,
    *,
    browser_outcome: dict | None = None,
) -> dict:
    scan = _scan_record(db, job.id)
    checked_at = datetime.now()
    report = {
        "job_id": job.id,
        "status": "complete",
        "found": 0,
        "read": 0,
        "unchanged": 0,
        "positions": 0,
        "errors": 0,
        "details": [],
    }
    try:
        links, _ = _fetch_job_page(job, browser_outcome)
    except DocumentFetchError as error:
        scan.status = "unavailable"
        scan.error = str(error)
        scan.checked_at = checked_at
        report["status"] = "unavailable"
        report["details"].append({"job_id": job.id, "error": str(error)})
        logger.warning("Official detail page could not be scanned for job %s: %s", job.id, error)
        db.flush()
        return report
    except Exception as error:
        scan.status = "unavailable"
        scan.error = f"İlan detay sayfası ayrıştırılamadı: {error}"
        scan.checked_at = checked_at
        report["status"] = "unavailable"
        report["details"].append({"job_id": job.id, "error": scan.error})
        logger.exception("Unexpected official detail page scan failure for job %s", job.id)
        db.flush()
        return report

    report["found"] = len(links)
    scan.attachments_found = len(links)
    scan.error = ""
    scan.checked_at = checked_at
    visited: set[str] = set()
    for link in links:
        _sync_document(db, job, link, visited, report)
    if report["errors"]:
        scan.status = "partial"
        scan.error = "; ".join(detail["error"] for detail in report["details"])
        report["status"] = "partial"
    else:
        scan.status = "complete"
    db.flush()
    return report


def sync_jobs_documents(db: Session, jobs: list[Job]) -> dict:
    scan_jobs = [
        job for job in jobs
        if "yerel yönetimler" not in (job.source_name or "").casefold()
        or "duyuru-" in (urlsplit(job.source_url or "").path.casefold())
    ]
    kariyer_jobs = [
        job for job in scan_jobs
        if "kariyer kapısı" in (job.source_name or "").casefold()
        and not _is_direct_document(job.source_url or "")
    ]
    outcomes: dict[str, dict] = {}
    browser_error = None
    if kariyer_jobs:
        try:
            outcomes = scrape_public_listing_details([
                {"url": job.source_url} for job in kariyer_jobs if job.source_url
            ])
        except Exception as error:
            browser_error = str(error)
            logger.exception("Kariyer Kapısı detail pages could not be scanned for attachments")

    aggregate = {
        "jobs_scanned": 0,
        "jobs_skipped": len(jobs) - len(scan_jobs),
        "attachments_found": 0,
        "documents_read": 0,
        "documents_unchanged": 0,
        "positions_extracted": 0,
        "errors": 0,
        "details": [],
        "details_omitted": 0,
    }
    for job in scan_jobs:
        outcome = outcomes.get(job.source_url or "")
        if browser_error and "kariyer kapısı" in (job.source_name or "").casefold():
            outcome = {"details": {}, "error": browser_error}
        report = sync_job_documents(db, job, browser_outcome=outcome)
        db.commit()
        aggregate["jobs_scanned"] += 1
        aggregate["attachments_found"] += report["found"]
        aggregate["documents_read"] += report["read"]
        aggregate["documents_unchanged"] += report["unchanged"]
        aggregate["positions_extracted"] += report["positions"]
        aggregate["errors"] += report["errors"] + int(report["status"] == "unavailable")
        if report["status"] != "complete" or report["details"]:
            remaining = max(0, 30 - len(aggregate["details"]))
            aggregate["details"].extend(report["details"][:remaining])
            aggregate["details_omitted"] += max(0, len(report["details"]) - remaining)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resmî ilan detay sayfalarındaki PDF, DOCX ve HTML eklerini indirip ayrıştırır."
    )
    parser.add_argument("--job-id", type=int, help="Yalnızca belirtilen ilanı tara.")
    parser.add_argument("--source", help="Yalnızca tam kaynak adını tara.")
    parser.add_argument("--limit", type=int, help="Taranacak ilan sayısını sınırla.")
    args = parser.parse_args()

    run_migrations()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        query = select(Job).where(Job.sector == "public").order_by(Job.id)
        if args.job_id is not None:
            query = query.where(Job.id == args.job_id)
        if args.source:
            query = query.where(Job.source_name == args.source)
        if args.limit is not None:
            query = query.limit(max(0, args.limit))
        jobs = list(db.scalars(query).all())
        report = sync_jobs_documents(db, jobs)
        db.commit()
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
