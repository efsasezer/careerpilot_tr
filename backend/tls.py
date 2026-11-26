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
            raise requests.exceptions.SSLError(
                f"certifi doğrulaması başarısız oldu ({certifi_error}); sistem deposuyla "
                f"doğrulama da başarısız: {system_error}"
            ) from system_error
