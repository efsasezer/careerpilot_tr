"""Taranmış (görüntü) PDF'ler için OCR.

Sistem paketi gerektirmez: sayfalar pypdfium2 ile görüntüye çevrilir ve RapidOCR (ONNX) ile
okunur. Paketler kurulu değilse, OCR kapatılmışsa ya da hata olursa çağıran taraf ilanı
"okunamadı" olarak bırakır; tarama ve uygulama durmaz.

Sınırlar: en çok MAX_PAGES sayfa, toplam MAX_SECONDS saniye; aynı anda tek belge işlenir.
"""

from __future__ import annotations

import os
import threading
import time

MAX_PAGES = 8
MAX_SECONDS = 90
LOW_CONFIDENCE = 0.80
_LOCK = threading.Lock()
_ENGINE = None


class OcrUnavailable(RuntimeError):
    pass


def ocr_enabled() -> bool:
    setting = os.getenv("CAREERPILOT_OCR", "").strip().casefold()
    if setting in {"0", "false", "off", "kapali"}:
        return False
    if setting in {"1", "true", "on", "acik"}:
        return True
    # Render'ın ücretsiz planında (512 MB) OCR belleğe sığmaz; açıkça istenmedikçe kapalıdır.
    return not os.getenv("RENDER")


def _engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as error:  # paket kurulu değil
            raise OcrUnavailable(f"OCR paketi kullanılamıyor: {error}") from error
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_pdf(body: bytes) -> dict:
    """PDF'i sayfa sayfa OCR'dan geçirir: {"text", "confidence", "pages", "truncated"}."""
    if not ocr_enabled():
        raise OcrUnavailable("OCR bu sunucuda kapalı (CAREERPILOT_OCR).")
    try:
        import numpy
        import pypdfium2
    except Exception as error:
        raise OcrUnavailable(f"OCR paketi kullanılamıyor: {error}") from error

    with _LOCK:  # aynı anda tek belge
        engine = _engine()
        started = time.monotonic()
        document = pypdfium2.PdfDocument(body)
        texts: list[str] = []
        scores: list[float] = []
        truncated = False
        try:
            total = len(document)
            for index in range(min(total, MAX_PAGES)):
                if time.monotonic() - started > MAX_SECONDS:
                    truncated = True
                    break
                page = document[index]
                image = numpy.array(page.render(scale=1.8).to_pil().convert("RGB"))
                result, _ = engine(image)
                del image
                lines = []
                for item in result or []:
                    lines.append(str(item[1]))
                    scores.append(float(item[2]))
                texts.append("\n".join(lines))
            truncated = truncated or total > MAX_PAGES
        finally:
            document.close()
    text = "\n\n".join(part for part in texts if part).strip()
    if len(text) < 80 or not scores:
        raise OcrUnavailable("OCR sayfalarda okunabilir metin bulamadı.")
    return {
        "text": text,
        "confidence": round(sum(scores) / len(scores), 3),
        "pages": len(texts),
        "truncated": truncated,
    }
