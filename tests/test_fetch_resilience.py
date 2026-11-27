"""Kaynak erişim hatalarının regresyon testleri (ağ kullanılmaz).

Üretimde görülen dört hata burada yeniden üretilir:
1. SBB Kamu İlanları: HTTP 403
2. Kariyer Kapısı: Page.wait_for_function zaman aşımı
3. Orta Anadolu Kalkınma Ajansı: "Ayrıştırılabilir ilan metni bulunamadı" (taranmış PDF)
4. Yerel Yönetimler: ConnectTimeoutError
"""

from datetime import date, datetime, timedelta

import pytest
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend import clock, sync, tls
from backend.database import Base
from backend.models import Job, JobEvent, SourceListing, SourceSyncHistory, UserJobState
from backend.sources import base
from backend.sources.base import SourceFetchError, classify_error, fetch_html


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


class _Response:
    def __init__(self, status=200, text="<html><body>" + "ilan " * 40 + "</body></html>", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.url, self.encoding, self.apparent_encoding = "https://ornek.gov.tr/", "utf-8", "utf-8"


def _serve(monkeypatch, outcomes):
    """tls.get yerine sırayla verilen yanıtları/istisnaları döndürür; çağrı sayısını ve beklemeleri kaydeder."""
    calls, sleeps = [], []
    queue = list(outcomes)

    def fake_get(url, **kwargs):
        calls.append(url)
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(tls, "get", fake_get)
    return calls, sleeps


# ---------------------------------------------------------------------------
# Hata türlerinin ayrılması
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("error, kind", [
    (requests.exceptions.ConnectTimeout("HTTPSConnectionPool(host='yerelyonetimler.csb.gov.tr', port=443): Max retries exceeded "
                                        "(Caused by ConnectTimeoutError(<HTTPSConnection>, 'Connection to host timed out. (connect timeout=8)'))"), "connect_timeout"),
    (requests.exceptions.ReadTimeout("Read timed out. (read timeout=40)"), "read_timeout"),
    (requests.exceptions.ConnectionError("Failed to resolve 'api.kariyerkapisi.gov.tr' ([Errno 8] nodename nor servname provided)"), "dns"),
    (requests.exceptions.SSLError("certificate verify failed: unable to get local issuer certificate"), "tls"),
    (requests.exceptions.ConnectionError("Connection aborted. RemoteDisconnected"), "connection"),
    (RuntimeError("Kariyer Kapısı ilan listesi 3 denemede yüklenemedi: Page.wait_for_function: Timeout 18000ms exceeded."), "browser_timeout"),
    (RuntimeError("page.goto: net::ERR_NAME_NOT_RESOLVED at https://kariyerkapisi.gov.tr/isealim"), "dns"),
    (ValueError("beklenmeyen"), "unknown"),
])
def test_errors_are_classified_by_layer(error, kind):
    assert classify_error(error) == kind


@pytest.mark.parametrize("status, kind", [(403, "http_403"), (404, "http_404"), (429, "http_429"), (500, "http_5xx"), (503, "http_5xx"), (302, "http_other")])
def test_http_statuses_are_classified(status, kind):
    assert classify_error(None, status) == kind
    assert SourceFetchError("Kaynak", "https://x", "hata", status).kind == kind


# ---------------------------------------------------------------------------
# Yeniden deneme davranışı
# ---------------------------------------------------------------------------

def test_403_is_not_retried_and_never_looks_like_an_empty_list(monkeypatch):
    calls, _ = _serve(monkeypatch, [_Response(403, "Forbidden")])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("SBB Kamu İlanları", "https://kamuilan.sbb.gov.tr/", sleep=lambda _: None)
    assert raised.value.kind == "http_403" and raised.value.status_code == 403
    assert len(calls) == 1  # aynı isteği yinelemek erişim kuralını değiştirmez


def test_404_is_not_retried(monkeypatch):
    calls, _ = _serve(monkeypatch, [_Response(404)])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("Kaynak", "https://ornek.gov.tr/yok", sleep=lambda _: None)
    assert raised.value.kind == "http_404" and len(calls) == 1


def test_429_honours_retry_after_and_then_succeeds(monkeypatch):
    waits = []
    calls, _ = _serve(monkeypatch, [_Response(429, headers={"Retry-After": "7"}), _Response(200)])
    final_url, body = fetch_html("Kaynak", "https://ornek.gov.tr/", sleep=waits.append)
    assert "ilan" in body and len(calls) == 2 and waits == [7.0]


def test_retry_after_is_capped_and_attempts_are_bounded(monkeypatch):
    waits = []
    calls, _ = _serve(monkeypatch, [_Response(503, headers={"Retry-After": "86400"})])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("Kaynak", "https://ornek.gov.tr/", sleep=waits.append)
    assert raised.value.kind == "http_5xx"
    assert len(calls) == base.MAX_ATTEMPTS and waits == [base.MAX_RETRY_WAIT] * (base.MAX_ATTEMPTS - 1)


def test_connect_timeout_is_retried_with_backoff_then_reported(monkeypatch):
    waits = []
    calls, _ = _serve(monkeypatch, [requests.exceptions.ConnectTimeout("connect timeout=15")])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("Yerel Yönetimler Genel Müdürlüğü", "https://yerelyonetimler.csb.gov.tr/duyurular", sleep=waits.append)
    assert raised.value.kind == "connect_timeout"
    assert len(calls) == base.MAX_ATTEMPTS and waits == [1.0, 3.0]


def test_certificate_failure_is_not_retried_or_bypassed(monkeypatch):
    calls, _ = _serve(monkeypatch, [requests.exceptions.SSLError("certificate verify failed")])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("Kaynak", "https://ornek.gov.tr/", sleep=lambda _: None)
    assert raised.value.kind == "tls" and len(calls) == 1
    with pytest.raises(ValueError):
        tls_get = __import__("importlib").reload(tls).get
        tls_get("https://ornek.gov.tr/", verify=False)


def test_block_page_with_http_200_is_an_error(monkeypatch):
    _serve(monkeypatch, [_Response(200, "<html>Request Rejected. Support ID: 1</html>")])
    with pytest.raises(SourceFetchError) as raised:
        fetch_html("Kaynak", "https://ornek.gov.tr/", sleep=lambda _: None)
    assert raised.value.kind == "blocked"


# ---------------------------------------------------------------------------
# Ara sertifika: yalnızca güvenilir köke kadar doğrulanan zincir kabul edilir
# ---------------------------------------------------------------------------

def _certificate(subject, issuer_name, issuer_key, key, *, ca, days=30):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID

    now = datetime.now()
    name = lambda text: x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])  # noqa: E731
    builder = (x509.CertificateBuilder().subject_name(name(subject)).issuer_name(name(issuer_name)).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=days))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    return builder.sign(issuer_key, hashes.SHA256())


def test_intermediate_is_accepted_only_when_it_chains_to_a_trusted_root():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding

    root_key, middle_key, leaf_key, rogue_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(4))
    root = _certificate("Güvenilir Kök", "Güvenilir Kök", root_key, root_key, ca=True)
    middle = _certificate("Ara Sertifika", "Güvenilir Kök", root_key, middle_key, ca=True)
    leaf = _certificate("webdosya.csb.gov.tr", "Ara Sertifika", middle_key, leaf_key, ca=False)
    leaf_der = leaf.public_bytes(Encoding.DER)

    assert tls.verified_intermediates(leaf_der, download=lambda _: middle, roots=[root]) == [middle]
    # Güvenilir köke bağlanmayan (sahte kökten gelen) ara sertifika reddedilir.
    rogue_root = _certificate("Sahte Kök", "Sahte Kök", rogue_key, rogue_key, ca=True)
    assert tls.verified_intermediates(leaf_der, download=lambda _: middle, roots=[rogue_root]) == []
    # Yaprağı imzalamamış bir sertifika ara sertifika olarak kabul edilmez.
    impostor = _certificate("Ara Sertifika", "Güvenilir Kök", root_key, rogue_key, ca=True)
    assert tls.verified_intermediates(leaf_der, download=lambda _: impostor, roots=[root]) == []
    # Süresi dolmuş ara sertifika reddedilir; indirilemezse de zincir kurulmaz.
    assert tls.verified_intermediates(leaf_der, download=lambda _: middle, roots=[root], now=datetime.now().astimezone() + timedelta(days=90)) == []
    assert tls.verified_intermediates(leaf_der, download=lambda _: None, roots=[root]) == []


# ---------------------------------------------------------------------------
# Tarama: başarısız kaynak veriyi silmez, diğer kaynakları durdurmaz
# ---------------------------------------------------------------------------

class _Source:
    pages_checked = 1

    def __init__(self, name, key, *, error=None, detail_error=None):
        self.source_name, self.key, self.error, self.detail_error = name, key, error, detail_error

    def fetch_listings(self):
        if self.error:
            raise self.error
        return [{
            "source_key": self.key, "source_name": self.source_name, "source_url": "https://ornek.gov.tr/",
            "detail_url": f"https://ornek.gov.tr/{self.key}/1", "external_id": f"{self.key}-1", "title": "3 Memur Alım İlanı",
            "institution": f"{self.source_name} Kurumu", "application_end_date": (date.today() + timedelta(days=5)).isoformat(),
            "content_hash": "liste",
        }]

    def fetch_detail(self, url):
        if self.detail_error:
            raise self.detail_error
        return {"source_text": "Herhangi bir lisans programından mezun olmak. " * 5, "content_hash": "detay", "detail_url": url}


def _run(db, registry):
    return sync.run_sync(db, registry=registry, scan_documents=False, check_results=False)


def test_the_four_production_failures_are_recorded_by_kind_and_keep_existing_data():
    db = _database()
    healthy = {key: _Source(name, key) for key, name in (("sbb", "SBB Kamu İlanları"), ("kk", "Kariyer Kapısı"), ("yerel", "Yerel Yönetimler"), ("iskur", "İŞKUR"))}
    _run(db, healthy)
    assert len(db.scalars(select(Job)).all()) == 4
    job = db.scalar(select(Job).where(Job.source_name == "SBB Kamu İlanları"))
    db.add(UserJobState(job_id=job.id, tracking="applied", notes="başvurdum", updated_at=datetime.now()))
    db.commit()
    events_before = len(db.scalars(select(JobEvent)).all())

    failing = {
        "sbb": _Source("SBB Kamu İlanları", "sbb", error=SourceFetchError("SBB Kamu İlanları", "https://kamuilan.sbb.gov.tr/", "Kaynak sayfası alınamadı.", 403)),
        "kk": _Source("Kariyer Kapısı", "kk", error=RuntimeError("Kariyer Kapısı ilan listesi 3 denemede yüklenemedi: Page.wait_for_function: Timeout 18000ms exceeded.")),
        "yerel": _Source("Yerel Yönetimler", "yerel", error=SourceFetchError(
            "Yerel Yönetimler", "https://yerelyonetimler.csb.gov.tr/duyurular", "ConnectTimeoutError (connect timeout=8)", kind="connect_timeout")),
        "iskur": _Source("İŞKUR", "iskur"),
    }
    report = _run(db, failing)
    assert {key: item["status"] for key, item in report["results"].items()} == {"sbb": "error", "kk": "error", "yerel": "error", "iskur": "ok"}
    kinds = {row.source_key: row.error_kind for row in db.scalars(
        select(SourceSyncHistory).order_by(SourceSyncHistory.id.desc()).limit(4)).all()}
    assert kinds == {"sbb": "http_403", "kk": "browser_timeout", "yerel": "connect_timeout", "iskur": ""}
    # Erişilemeyen kaynakların ilanları, olayları ve kullanıcının işaretlemeleri yerinde durur.
    assert len(db.scalars(select(Job).where(Job.archived_reason == "")).all()) == 4
    assert len(db.scalars(select(JobEvent)).all()) == events_before
    assert db.get(UserJobState, job.id).tracking == "applied" and db.get(UserJobState, job.id).notes == "başvurdum"
    assert report["success"] is False  # kısmi başarısızlık "başarılı tarama" olarak raporlanmaz


def test_repeated_scans_do_not_duplicate_listings_or_events():
    db = _database()
    registry = {"sbb": _Source("SBB Kamu İlanları", "sbb")}
    _run(db, registry)
    counts = (len(db.scalars(select(Job)).all()), len(db.scalars(select(SourceListing)).all()), len(db.scalars(select(JobEvent)).all()))
    second = _run(db, registry)
    assert second["results"]["sbb"]["imported"] == 0 and second["results"]["sbb"]["unchanged"] == 1
    assert (len(db.scalars(select(Job)).all()), len(db.scalars(select(SourceListing)).all()), len(db.scalars(select(JobEvent)).all())) == counts


def test_scanned_pdf_is_reported_as_scanned_not_as_generic_parse_failure(monkeypatch):
    """Orta Anadolu Kalkınma Ajansı ilanı: sayfaları görüntü olan PDF'te yalnızca birkaç karakter metin var."""
    from backend import documents, ocr

    monkeypatch.setattr(documents, "parse_document", lambda url, body, content_type: {
        "text": "T.C. ORAN 1/10", "shared_requirements": "", "positions": [], "links": []})
    monkeypatch.setattr(base, "pdf_is_scanned", lambda body: True)

    def unavailable(_body):
        raise ocr.OcrUnavailable("OCR bu sunucuda kapalı (CAREERPILOT_OCR).")

    monkeypatch.setattr(ocr, "ocr_pdf", unavailable)
    with pytest.raises(documents.ScannedDocumentError, match="Taranmış PDF"):
        base.BaseJobSource.document_detail("https://www.iskur.gov.tr/medya/ilan.pdf", b"%PDF-1.5 ...", "application/pdf")

    monkeypatch.setattr(ocr, "ocr_pdf", lambda _body: {"text": "Orta Anadolu Kalkınma Ajansı personel alım ilanı " * 20, "confidence": 0.87})
    detail = base.BaseJobSource.document_detail("https://www.iskur.gov.tr/medya/ilan.pdf", b"%PDF-1.5 ...", "application/pdf")
    assert "Kalkınma Ajansı" in detail["source_text"] and detail["document"]["parsed"]["ocr_confidence"] == 0.87


def test_short_text_pdf_with_a_real_text_layer_is_not_treated_as_scanned(monkeypatch):
    from backend import documents

    monkeypatch.setattr(documents, "parse_document", lambda url, body, content_type: {
        "text": "Başvurular 09/12/2026 - 11/12/2026", "shared_requirements": "", "positions": [], "links": []})
    detail = base.BaseJobSource.document_detail("https://ornek.gov.tr/a.pdf", b"%PDF-1.5 sahte", "application/pdf")
    assert detail["source_text"].startswith("Başvurular")


def test_unreadable_listing_is_kept_and_marked_while_scan_continues():
    from backend.documents import ScannedDocumentError

    db = _database()
    report = _run(db, {
        "iskur": _Source("İŞKUR", "iskur", detail_error=ScannedDocumentError("Taranmış PDF okunamadı: OCR bu sunucuda kapalı")),
        "sbb": _Source("SBB Kamu İlanları", "sbb"),
    })
    assert report["results"]["iskur"]["status"] == "partial" and report["results"]["sbb"]["status"] == "ok"
    listing = db.scalar(select(SourceListing).where(SourceListing.source_key == "iskur"))
    assert listing.status == "unreadable" and db.get(Job, listing.job_id) is not None


# ---------------------------------------------------------------------------
# Tarama kilidi
# ---------------------------------------------------------------------------

def test_only_one_scan_runs_at_a_time_and_stale_lock_is_taken_over():
    db = _database()
    assert sync.acquire_scan_lock(db, "birinci")
    assert not sync.acquire_scan_lock(db, "ikinci")
    with pytest.raises(sync.ScanAlreadyRunning):
        sync.run_sync_locked(db, registry={}, scan_documents=False, check_results=False)
    assert sync.acquire_scan_lock(db, "ikinci", now=clock.now() + sync.LOCK_LEASE + timedelta(seconds=1))
    sync.release_scan_lock(db, "ikinci")
    report = sync.run_sync_locked(db, registry={}, scan_documents=False, check_results=False)
    assert report["results"] == {} and sync.acquire_scan_lock(db, "üçüncü")  # tarama bitince kilit bırakılmıştır
