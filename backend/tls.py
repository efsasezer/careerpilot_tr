"""Eksik ara sertifika gönderen resmî sunucular için güvenli zincir tamamlama.

Bazı .gov.tr sunucuları yalnızca kendi sertifikasını gönderir; ara sertifikayı göndermez.
Tarayıcılar bu durumda sertifikadaki "CA Issuers" (AIA) adresinden ara sertifikayı indirir.
Burada aynısı yapılır: ara sertifika güven deposuna *kök olarak* eklenmez; zincir yine
certifi'deki güvenilir bir köke kadar doğrulanmak zorundadır. Doğrulama hiçbir zaman kapatılmaz.
"""

from __future__ import annotations

import socket
import ssl
import tempfile
import threading
from pathlib import Path

import certifi
import requests

_LOCK = threading.Lock()
_BUNDLES: dict[str, str] = {}
_ALLOWED_SUFFIXES = (".gov.tr",)


def _leaf_certificate(host: str) -> bytes:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # yalnızca sertifikayı okumak için; veri alışverişi yapılmaz
    with socket.create_connection((host, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def _issuer_urls(der: bytes) -> list[str]:
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    certificate = x509.load_der_x509_certificate(der)
    try:
        access = certificate.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return []
    return [
        item.access_location.value
        for item in access
        if item.access_method == AuthorityInformationAccessOID.CA_ISSUERS
        and item.access_location.value.startswith("http://")
    ]


def _to_pem(body: bytes) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    try:
        certificate = x509.load_der_x509_certificate(body)
    except ValueError:
        certificate = x509.load_pem_x509_certificate(body)
    return certificate.public_bytes(Encoding.PEM).decode("ascii")


def ca_bundle_for(host: str) -> str:
    """`requests(..., verify=...)` için kullanılacak CA dosyasının yolunu döndürür."""
    host = host.casefold().rstrip(".")
    if not host.endswith(_ALLOWED_SUFFIXES):
        return certifi.where()
    with _LOCK:
        if host in _BUNDLES:
            return _BUNDLES[host]
        bundle = certifi.where()
        try:
            intermediates = []
            der = _leaf_certificate(host)
            for _ in range(3):  # en çok üç ara sertifika
                urls = _issuer_urls(der)
                if not urls:
                    break
                response = requests.get(urls[0], timeout=15)
                if response.status_code != 200 or len(response.content) > 20_000:
                    break
                pem = _to_pem(response.content)
                intermediates.append(pem)
                der = ssl.PEM_cert_to_DER_cert(pem)
            if intermediates:
                handle = tempfile.NamedTemporaryFile("w", suffix=".pem", prefix="careerpilot-ca-", delete=False)
                with handle:
                    handle.write(Path(certifi.where()).read_text(encoding="utf-8"))
                    handle.write("\n" + "\n".join(intermediates))
                bundle = handle.name
        except Exception:
            bundle = certifi.where()  # tamamlanamazsa normal doğrulama (ve hatası) geçerli olur
        _BUNDLES[host] = bundle
        return bundle


def get(url: str, *, session: requests.Session | None = None, **kwargs) -> requests.Response:
    """requests.get; sertifika zinciri eksikse ara sertifikayı tamamlayıp bir kez yeniden dener."""
    from urllib.parse import urlsplit

    client = session or requests
    try:
        return client.get(url, **kwargs)
    except requests.exceptions.SSLError:
        host = urlsplit(url).hostname or ""
        bundle = ca_bundle_for(host)
        if bundle == certifi.where():
            raise
        return client.get(url, verify=bundle, **kwargs)
