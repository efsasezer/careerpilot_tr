"""Use the platform trust store as a verified fallback for official .gov.tr hosts."""

from __future__ import annotations

import ssl
import threading
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

_SYSTEM_SESSIONS = threading.local()
_SYSTEM_SESSION_LOCK = threading.Lock()


class _SystemTrustAdapter(HTTPAdapter):
    def __init__(self) -> None:
        self._ssl_context = ssl.create_default_context()
        if self._ssl_context.verify_mode != ssl.CERT_REQUIRED or not self._ssl_context.check_hostname:
            raise RuntimeError("Sistem sertifika deposu doğrulaması etkin değil.")
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def cert_verify(self, conn, url, verify, cert):
        if verify is not True:
            raise ValueError("Platform trust fallback yalnızca varsayılan TLS doğrulamasıyla kullanılabilir.")
        conn.cert_reqs = "CERT_REQUIRED"
        conn.ca_certs = None
        conn.ca_cert_dir = None
        if cert:
            super().cert_verify(conn, url, verify, cert)
            conn.ca_certs = None
            conn.ca_cert_dir = None


def _system_trust_session(host: str, session: requests.Session | None) -> requests.Session:
    if session is not None:
        client = session
    else:
        sessions = getattr(_SYSTEM_SESSIONS, "by_host", None)
        if sessions is None:
            sessions = {}
            _SYSTEM_SESSIONS.by_host = sessions
        with _SYSTEM_SESSION_LOCK:
            client = sessions.get(host)
            if client is None:
                client = requests.Session()
                sessions[host] = client

    prefix = f"https://{host}/"
    if not isinstance(client.get_adapter(prefix), _SystemTrustAdapter):
        client.mount(prefix, _SystemTrustAdapter())
    return client


def get(url: str, *, session: requests.Session | None = None, **kwargs) -> requests.Response:
    """Retry a certificate-store mismatch through the platform's verified trust store."""
    client = session or requests
    requested_verify = kwargs.get("verify")
    if requested_verify is None:
        requested_verify = getattr(session, "verify", True)
    if requested_verify is False:
        raise ValueError("TLS sertifika doğrulaması devre dışı bırakılamaz.")

    try:
        return client.get(url, **kwargs)
    except requests.exceptions.SSLError as certifi_error:
        host = urlsplit(url).hostname or ""
        if (
            requested_verify is not True
            or not host.casefold().endswith(".gov.tr")
        ):
            raise
        fallback = _system_trust_session(host, session)
        try:
            return fallback.get(url, **kwargs)
        except requests.exceptions.SSLError as system_error:
            # Sunucu ara sertifikayı göndermiyorsa (ör. webdosya.csb.gov.tr) zincir, sertifikanın
            # kendi "CA Issuers" adresinden tamamlanır. Doğrulama kapatılmaz: ara sertifika ancak
            # certifi'deki güvenilir bir köke kadar imza zinciri kanıtlanırsa kullanılır.
            bundle = completed_ca_bundle(host)
            if bundle is None:
                raise requests.exceptions.SSLError(
                    f"certifi doğrulaması başarısız oldu ({certifi_error}); sistem deposuyla "
                    f"doğrulama da başarısız: {system_error}"
                ) from system_error
            return client.get(url, **{**kwargs, "verify": bundle})


# ---------------------------------------------------------------------------
# Eksik ara sertifikanın doğrulanarak tamamlanması (AIA)
# ---------------------------------------------------------------------------

_BUNDLES: dict[str, str | None] = {}
_BUNDLE_LOCK = threading.Lock()
MAX_INTERMEDIATES = 3


def _leaf_certificate(host: str) -> bytes:
    import socket

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # yalnızca sertifikayı okumak için; veri alışverişi yapılmaz
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secured:
            return secured.getpeercert(binary_form=True)


def _download_issuer(certificate):
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    try:
        access = certificate.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    for item in access:
        location = getattr(item.access_location, "value", "")
        if item.access_method != AuthorityInformationAccessOID.CA_ISSUERS or not location.startswith("http://"):
            continue
        response = requests.get(location, timeout=15)
        if response.status_code != 200 or len(response.content) > 20_000:
            continue
        try:
            return x509.load_der_x509_certificate(response.content)
        except ValueError:
            return x509.load_pem_x509_certificate(response.content)
    return None


def verified_intermediates(leaf_der: bytes, *, download=_download_issuer, roots=None, now=None) -> list:
    """Yaprak sertifikadan güvenilir bir köke kadar imzası doğrulanan ara sertifikaları döndürür.

    Zincirin her halkası bir üstündeki sertifikayla imzalanmış ve geçerlilik süresi içinde olmalı;
    en üstteki halka certifi'deki bir kök tarafından imzalanmış olmalıdır. Aksi hâlde boş liste döner
    ve bağlantı reddedilir.
    """
    from datetime import datetime, timezone

    import certifi
    from cryptography import x509

    now = now or datetime.now(timezone.utc)
    if roots is None:
        roots = x509.load_pem_x509_certificates(open(certifi.where(), "rb").read())
    current = x509.load_der_x509_certificate(leaf_der)
    chain = []
    for _ in range(MAX_INTERMEDIATES):
        issuer = download(current)
        if issuer is None or not (issuer.not_valid_before_utc <= now <= issuer.not_valid_after_utc):
            return []
        try:
            current.verify_directly_issued_by(issuer)
        except Exception:
            return []
        chain.append(issuer)
        for root in roots:
            if root.subject != issuer.issuer:
                continue
            try:
                issuer.verify_directly_issued_by(root)
            except Exception:
                continue
            return chain
        current = issuer
    return []


def completed_ca_bundle(host: str) -> str | None:
    """certifi kökleri + doğrulanmış ara sertifikalar içeren CA dosyası; kurulamazsa None."""
    import tempfile

    import certifi
    from cryptography.hazmat.primitives.serialization import Encoding

    host = host.casefold().rstrip(".")
    with _BUNDLE_LOCK:
        if host in _BUNDLES:
            return _BUNDLES[host]
        bundle = None
        try:
            chain = verified_intermediates(_leaf_certificate(host))
            if chain:
                handle = tempfile.NamedTemporaryFile("w", suffix=".pem", prefix="careerpilot-ca-", delete=False)
                with handle:
                    handle.write(open(certifi.where(), encoding="utf-8").read())
                    for certificate in chain:
                        handle.write("\n" + certificate.public_bytes(Encoding.PEM).decode("ascii"))
                bundle = handle.name
        except Exception:
            bundle = None
        _BUNDLES[host] = bundle
        return bundle
