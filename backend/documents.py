from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import re
import socket
from urllib.parse import unquote, urljoin, urlsplit

import pdfplumber
import requests
from docx import Document


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_TEXT = 1_000_000
DOCUMENT_LABELS = (
    "tablo", "kadro", "pozisyon", "başvuru şart", "başvuru kılavuz",
    "öğrenim şart", "nitelik", "atama şart", "görev şart", "ek belge",
)
TRUSTED_GOVERNMENT_DOMAINS = (
    "kariyerkapisi.gov.tr",
    "sbb.gov.tr",
    "iskur.gov.tr",
    "csb.gov.tr",
)


class DocumentFetchError(RuntimeError):
    pass


class DocumentParseError(RuntimeError):
    pass


def _validate_official_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or (parsed.port is not None and parsed.port != 443)
        or not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in TRUSTED_GOVERNMENT_DOMAINS
        )
    ):
        raise DocumentFetchError("Yalnızca izin verilen resmî .gov.tr belge bağlantıları açılabilir.")

    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except OSError as error:
        raise DocumentFetchError(f"Resmî belge sunucusu çözümlenemedi: {error}") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise DocumentFetchError("Belge bağlantısı genel erişimli bir resmî sunucuya yönlenmiyor.")
    return url


def fetch_url(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> dict:
    headers = {"User-Agent": "CareerPilotTR/1.0 (official public recruitment attachments)"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    current_url = url
    for _ in range(6):
        _validate_official_url(current_url)
        try:
            response = requests.get(
                current_url,
                headers=headers,
                timeout=(8, 35),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            raise DocumentFetchError(f"Resmî belge alınamadı: {error}") from error

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise DocumentFetchError("Belge yönlendirmesinde hedef adres bulunamadı.")
            current_url = urljoin(current_url, location)
            continue
        if response.status_code == 304:
            response.close()
            return {
                "not_modified": True,
                "url": current_url,
                "etag": response.headers.get("ETag") or etag,
                "last_modified": response.headers.get("Last-Modified") or last_modified,
                "content_type": response.headers.get("Content-Type", ""),
                "body": b"",
            }
        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise DocumentFetchError(f"Resmî belge sunucusu HTTP {status} döndürdü.")

        chunks = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise DocumentFetchError(
                        f"Belge {max_bytes // (1024 * 1024)} MB boyut sınırını aşıyor."
                    )
                chunks.append(chunk)
            final_url = response.url
            content_type = response.headers.get("Content-Type", "")
            etag_value = response.headers.get("ETag")
            modified_value = response.headers.get("Last-Modified")
        except requests.RequestException as error:
            raise DocumentFetchError(f"Belge indirme sırasında bağlantı kesildi: {error}") from error
        finally:
            response.close()

        _validate_official_url(final_url)
        return {
            "not_modified": False,
            "url": final_url,
            "etag": etag_value,
            "last_modified": modified_value,
            "content_type": content_type,
            "body": b"".join(chunks),
        }

    raise DocumentFetchError("Belge bağlantısı çok sayıda yönlendirme yaptı.")


class _HTMLDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self.text_parts: list[str] = []
        self.narrative_parts: list[str] = []
        self._anchor: dict[str, str] | None = None
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if self._ignored_depth:
            return
        if tag == "a":
            self._anchor = {"href": values.get("href") or "", "text": ""}
        elif tag == "table":
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag in {"br", "p", "div", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._ignored_depth:
            return
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join(self._anchor["text"].split())
            if self._anchor["href"]:
                self.anchors.append(self._anchor)
            self._anchor = None
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None
        elif tag in {"p", "div", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = data.strip()
        if not text:
            return
        self.text_parts.append(f"{text} ")
        if self._table is None:
            self.narrative_parts.append(text)
        if self._anchor is not None:
            self._anchor["text"] += f" {text}"
        if self._cell is not None:
            self._cell.append(text)


def discover_document_links(page_url: str, html: str) -> list[dict[str, str]]:
    parser = _HTMLDocumentParser()
    parser.feed(html or "")
    page = urlsplit(page_url)
    found: dict[str, dict[str, str]] = {}
    for anchor in parser.anchors:
        candidate_url = urljoin(page_url, anchor["href"].strip())
        parsed = urlsplit(candidate_url)
        path = unquote(parsed.path).casefold()
        suffix = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
        label = anchor["text"].strip()
        likely_document = _is_document_candidate(suffix, label)
        if not likely_document or candidate_url == page_url:
            continue
        try:
            _validate_official_url(candidate_url)
        except DocumentFetchError:
            continue
        candidate = urlsplit(candidate_url)
        if candidate.hostname == page.hostname and candidate.path == page.path and candidate.query == page.query:
            continue
        found.setdefault(candidate_url, {
            "url": candidate_url,
            "title": label or unquote(path.rsplit("/", 1)[-1]) or candidate.hostname or "",
        })
    return list(found.values())


def _is_document_candidate(suffix: str, label: str) -> bool:
    if suffix in {".pdf", ".docx", ".doc", ".rtf"}:
        return True
    normalized_label = " ".join((label or "").casefold().split())
    return (
        any(marker in normalized_label for marker in DOCUMENT_LABELS)
        or re.search(r"\bek(?:[-\s]\d+)?\b", normalized_label) is not None
    )


def filter_document_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for link in links:
        candidate_url = str(link.get("url") or "").strip()
        if not candidate_url:
            continue
        path = unquote(urlsplit(candidate_url).path).casefold()
        suffix = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
        title = str(link.get("title") or "").strip()
        if not _is_document_candidate(suffix, title):
            continue
        try:
            _validate_official_url(candidate_url)
        except DocumentFetchError:
            continue
        found.setdefault(candidate_url, {"url": candidate_url, "title": title})
    return list(found.values())


def _normalize_header(value: str) -> str:
    translation = str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    })
    return re.sub(r"\s+", " ", (value or "").translate(translation).casefold()).strip()


def _position_title(education: str) -> str:
    normalized = " ".join((education or "").split())
    title_match = re.search(
        r"([^,;]+?\b(?:mühendisliği|mühendisi|teknikerliği|teknikeri)\b)",
        normalized,
        re.I,
    )
    if title_match:
        candidate = title_match.group(1).strip(" ,;.")
        if "üniversitelerin" in candidate.casefold() and "ziraat mühendisi" in candidate.casefold():
            return "Ziraat Mühendisi"
        return candidate[:250]
    if normalized:
        candidate = normalized.split(",", 1)[0].strip(" ,;.")
        candidate = re.split(
            r"\s+(?:lisans|ön lisans|programlar)",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]
        return candidate[:250]
    return ""


def _mandatory_requirement_text(text: str) -> str:
    markers = (
        "olmak", "olması", "olmamak", "taşımak", "taşımaları", "gerekmektedir",
        "zorunludur", "sahip olmak", "bulunmamak", "şartı", "şartlarını",
        "en az", "en fazla", "aranmaktadır",
    )
    prepared = re.sub(r"(?<![.!?:;])\s*\n\s*", " ", text or "")
    sentences = re.split(r"(?<=[.!?])\s+", prepared)
    selected = []
    seen = set()
    for sentence in sentences:
        cleaned = " ".join(sentence.split()).strip()
        normalized = _normalize_header(cleaned)
        if not cleaned or not any(marker in normalized for marker in (
            _normalize_header(value) for value in markers
        )):
            continue
        if any(phrase in normalized for phrase in (
            "sinava cagrilacak", "sinava katilacak", "sinav konulari",
            "puanina gore siralan", "en yuksek puan",
        )):
            continue
        if normalized not in seen:
            selected.append(cleaned)
            seen.add(normalized)
    return "\n".join(selected)


def _table_positions_from_matrix(matrix: list[list[str]]) -> list[dict]:
    if len(matrix) < 2:
        return []
    headers = [_normalize_header(cell) for cell in matrix[0]]

    education_idx = next(
        (i for i, value in enumerate(headers) if "ogrenim" in value or "mezuniyet" in value),
        None,
    )
    quota_idx = next(
        (i for i, value in enumerate(headers) if "pozisyon" in value and "sayisi" in value),
        None,
    )
    score_idx = next(
        (i for i, value in enumerate(headers) if "puan tur" in value or "kpss puan" in value),
        None,
    )
    minimum_idx = next(
        (i for i, value in enumerate(headers) if "taban puan" in value),
        None,
    )
    city_idx = next(
        (i for i, value in enumerate(headers) if "atanacag" in value or "gorev yeri" in value),
        None,
    )
    exam_idx = next(
        (i for i, value in enumerate(headers) if "sinav" in value and "aday" in value),
        None,
    )
    if education_idx is None or quota_idx is None:
        return []

    positions = []
    for row_index, row in enumerate(matrix[1:], 1):
        cells = row + [""] * max(0, len(headers) - len(row))
        quota = cells[quota_idx].strip()
        if not re.fullmatch(r"\d+(?:\s*(?:kişi|adet))?", quota, re.I):
            continue
        education = cells[education_idx].strip()
        if not education:
            continue
        position = {
            "row_index": row_index,
            "position_title": _position_title(education),
            "education_requirement": education,
            "quota": re.search(r"\d+", quota).group(0),
            "kpss_score_type": "",
            "kpss_min_score": None,
            "city": cells[city_idx].strip() if city_idx is not None else "",
            "qualification_codes": "",
            "written_exam_invite_text": cells[exam_idx].strip() if exam_idx is not None else "",
            "written_exam_invite_count": None,
            "requirements_text": education,
            "raw_cells": dict(zip(headers, cells)),
        }
        if score_idx is not None:
            score_value = cells[score_idx].upper()
            score_match = re.search(r"\bP\d{1,2}\b", score_value)
            if score_match:
                position["kpss_score_type"] = score_match.group(0)
        if minimum_idx is not None:
            minimum = re.search(r"\d{2,3}(?:[.,]\d+)?", cells[minimum_idx])
            if minimum:
                position["kpss_min_score"] = float(minimum.group(0).replace(",", "."))
        codes = re.findall(r"(?<!\d)\d{4}(?!\d)", " ".join(cells))
        position["qualification_codes"] = ", ".join(sorted(set(codes)))
        exam_match = re.search(
            r"(\d+)\s*\([^)]{1,30}\)\s*kat",
            _normalize_header(position["written_exam_invite_text"]),
        )
        if exam_match:
            position["written_exam_invite_count"] = int(exam_match.group(1))
        positions.append(position)
    return positions


def _pdf_table_positions(page) -> tuple[list[dict], tuple[float, float, float, float] | None]:
    candidates = []
    for table in page.find_tables():
        if not table.rows:
            continue
        header_cells = table.rows[0].cells
        header_text: dict[int, str] = {}
        for index, cell in enumerate(header_cells):
            if cell:
                header_text[index] = (page.crop(cell).extract_text() or "").strip()
        normalized = {index: _normalize_header(value) for index, value in header_text.items()}

        def find_header(predicate):
            return next((index for index, value in normalized.items() if predicate(value)), None)

        quota_idx = find_header(lambda value: "pozisyon" in value and "sayisi" in value)
        exam_idx = find_header(lambda value: "sinav" in value and "aday" in value)
        minimum_idx = find_header(lambda value: "taban" in value and "puan" in value)
        education_idx = find_header(lambda value: "ogrenim" in value or "mezuniyet" in value)
        city_idx = find_header(lambda value: "atanacag" in value or "gorev yeri" in value)
        if None in {quota_idx, minimum_idx, education_idx, city_idx}:
            continue
        candidates.append((table, quota_idx, exam_idx, minimum_idx, education_idx, city_idx))

    if not candidates:
        return [], None
    table, quota_idx, exam_idx, minimum_idx, education_idx, city_idx = max(
        candidates, key=lambda item: len(item[0].rows)
    )
    header_cells = table.rows[0].cells
    quota_header = header_cells[quota_idx]
    minimum_header = header_cells[minimum_idx]
    education_header = header_cells[education_idx]
    city_header = header_cells[city_idx]
    if not all((quota_header, minimum_header, education_header, city_header)):
        return [], None
    score_left = header_cells[exam_idx][2] if exam_idx is not None and header_cells[exam_idx] else quota_header[2]
    score_right = minimum_header[0]
    positions = []
    for row_index, row in enumerate(table.rows[1:], 1):
        if quota_idx >= len(row.cells):
            continue
        quota_cell = row.cells[quota_idx]
        if not quota_cell:
            continue
        quota_text = (page.crop(quota_cell).extract_text() or "").strip()
        if not re.fullmatch(r"\d+(?:\s*(?:kişi|adet))?", quota_text, re.I):
            continue
        top, bottom = quota_cell[1], quota_cell[3]
        middle = (top + bottom) / 2

        def cell_text_in_column(column_index: int | None) -> str:
            if column_index is None:
                return ""
            matches = []
            for candidate_row in table.rows[1:]:
                if column_index >= len(candidate_row.cells):
                    continue
                cell = candidate_row.cells[column_index]
                if cell and cell[1] <= middle <= cell[3]:
                    matches.append(cell)
            if not matches:
                return ""
            cell = min(matches, key=lambda value: value[3] - value[1])
            return (page.crop(cell).extract_text() or "").strip()

        education = (page.crop((
            table.bbox[0], top, quota_header[0], bottom
        )).extract_text() or "").strip()
        if not education:
            education = cell_text_in_column(education_idx)
        score_text = (page.crop((
            score_left, top, score_right, bottom
        )).extract_text() or "").strip()
        minimum_text = (page.crop((
            minimum_header[0], top, minimum_header[2], bottom
        )).extract_text() or "").strip()
        city_text = (page.crop((
            city_header[0], top, table.bbox[2], bottom
        )).extract_text() or "").strip()
        exam_text = cell_text_in_column(exam_idx)
        quota = re.search(r"\d+", quota_text)
        score = re.search(r"\bP\d{1,2}\b", score_text.upper())
        minimum = re.search(r"\d{2,3}(?:[.,]\d+)?", minimum_text)
        exam_count = re.search(
            r"(\d+)\s*\([^)]{1,30}\)\s*kat",
            _normalize_header(exam_text),
        )
        positions.append({
            "row_index": row_index,
            "position_title": _position_title(education),
            "education_requirement": education,
            "quota": quota.group(0) if quota else "",
            "kpss_score_type": score.group(0) if score else "",
            "kpss_min_score": float(minimum.group(0).replace(",", ".")) if minimum else None,
            "city": city_text,
            "qualification_codes": ", ".join(sorted(set(
                re.findall(r"(?<!\d)\d{4}(?!\d)", education)
            ))),
            "written_exam_invite_text": exam_text,
            "written_exam_invite_count": int(exam_count.group(1)) if exam_count else None,
            "requirements_text": education,
            "raw_cells": {
                "education": education,
                "quota": quota_text,
                "kpss": score_text,
                "minimum": minimum_text,
                "city": city_text,
                "written_exam_invite": exam_text,
            },
        })
    return positions, table.bbox


def _parse_pdf(body: bytes) -> dict:
    try:
        with pdfplumber.open(BytesIO(body)) as pdf:
            texts = []
            positions = []
            shared_texts = []
            for page in pdf.pages[:100]:
                page_text = page.extract_text() or ""
                texts.append(page_text)
                page_positions, table_bounds = _pdf_table_positions(page)
                positions.extend(page_positions)
                if not page_positions:
                    shared_texts.append(page_text)
                elif table_bounds:
                    if table_bounds[1] > 1:
                        shared_texts.append(
                            page.crop((0, 0, page.width, table_bounds[1])).extract_text() or ""
                        )
                    if table_bounds[3] < page.height - 1:
                        shared_texts.append(
                            page.crop((0, table_bounds[3], page.width, page.height)).extract_text() or ""
                        )
            if len(pdf.pages) > 100:
                raise DocumentParseError("PDF 100 sayfa sınırını aşıyor; otomatik ayrıştırma durduruldu.")
    except DocumentParseError:
        raise
    except Exception as error:
        raise DocumentParseError(f"PDF metin ve tablo ayrıştırması başarısız: {error}") from error
    text = "\n\n".join(value for value in texts if value).strip()
    if not text:
        raise DocumentParseError("PDF'de ayrıştırılabilir metin bulunamadı; taranmış görüntü OCR gerektiriyor.")
    return {
        "text": text[:MAX_EXTRACTED_TEXT],
        "shared_requirements": _mandatory_requirement_text(
            "\n\n".join(value for value in shared_texts if value)
        )[:MAX_EXTRACTED_TEXT],
        "positions": positions,
        "links": [],
        "partially_read": "\ufffd" in text,
    }


def _positions_from_html_tables(tables: list[list[list[str]]]) -> list[dict]:
    positions = []
    for table in tables:
        if not table:
            continue
        candidates = _table_positions_from_matrix(table)
        if candidates:
            positions.extend(candidates)
    return positions


def parse_document(url: str, body: bytes, content_type: str = "") -> dict:
    path = unquote(urlsplit(url).path).casefold()
    suffix = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    content_type = content_type.casefold()

    if body.startswith(b"%PDF-") or suffix == ".pdf" or "application/pdf" in content_type:
        parsed = _parse_pdf(body)
    elif suffix == ".docx" or "wordprocessingml" in content_type:
        try:
            document = Document(BytesIO(body))
        except Exception as error:
            raise DocumentParseError(f"DOCX belgesi açılamadı: {error}") from error
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        tables = [
            [[cell.text.strip() for cell in row.cells] for row in table.rows]
            for table in document.tables
        ]
        parsed = {
            "text": "\n".join(paragraphs + [
                "\n".join(" | ".join(row) for row in table) for table in tables
            ])[:MAX_EXTRACTED_TEXT],
            "shared_requirements": _mandatory_requirement_text(
                "\n".join(paragraphs)
            )[:MAX_EXTRACTED_TEXT],
            "positions": _positions_from_html_tables(tables),
            "links": [],
            "partially_read": False,
        }
    elif suffix in {".doc", ".rtf"}:
        raise DocumentParseError("Bu belge biçimi desteklenmiyor; PDF, DOCX ve HTML okunabiliyor.")
    elif "text/html" in content_type or suffix in {".html", ".htm", ".aspx"}:
        parser = _HTMLDocumentParser()
        try:
            parser.feed(body.decode("utf-8", errors="replace"))
        except Exception as error:
            raise DocumentParseError(f"HTML belgesi ayrıştırılamadı: {error}") from error
        parsed = {
            "text": "\n".join(parser.text_parts)[:MAX_EXTRACTED_TEXT],
            "shared_requirements": _mandatory_requirement_text(
                "\n".join(parser.narrative_parts)
            )[:MAX_EXTRACTED_TEXT],
            "positions": _positions_from_html_tables(parser.tables),
            "links": discover_document_links(url, body.decode("utf-8", errors="replace")),
            "partially_read": "\ufffd" in "".join(parser.text_parts),
        }
    else:
        raise DocumentParseError(
            f"Belge biçimi tanınmıyor (Content-Type: {content_type or 'belirtilmedi'})."
        )

    if len(parsed["text"].strip()) < 20:
        raise DocumentParseError("Belgede okunabilir metin bulunamadı.")
    return parsed
