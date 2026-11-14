from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit

from ..eligibility import detect_recruitment_method, normalize_text
from .base import (
    BaseJobSource,
    absolute_url,
    content_hash,
    external_id,
    fetch_html,
    parse_html_page,
)


_DATE_RANGE = re.compile(
    r"\(?\s*(\d{1,2})\s+([\wçğıöşü]+)\s*[-–]\s*"
    r"(\d{1,2})\s+([\wçğıöşü]+)\s*\)?\s*$",
    re.IGNORECASE,
)
_MONTHS = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}
_ORGANIZATION_SUFFIXES = (
    "üniversitesi",
    "bakanlığı",
    "başkanlığı",
    "genel müdürlüğü",
    "müdürlüğü",
    "ajansı",
    "komutanlığı",
    "kurulu",
    "kurumu",
    "idaresi",
    "enstitüsü",
)
_QUOTA_ROLE = re.compile(
    r"^(?:proje\s+bazlı\s+)?(?:adet\s+)?"
    r"(?:destek\s+personeli?|sözleşmeli|memur|personel|işçi|stajyer|uzman|mühendis|tekniker|"
    r"teknisyen|öğretim|zabıta|itfaiye|psikolog|denetmen|kontrolör)\b",
    re.IGNORECASE,
)


def _extract_quota(title: str) -> str | None:
    parts = [part.strip() for part in title.split(",")]
    counted_roles = []
    for part in parts:
        part = re.split(
            r"\b(?:alacak|edilecek|temin)\b",
            part,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        match = re.match(r"^(\d+)\s+(.+)$", part)
        if match and _QUOTA_ROLE.match(match.group(2)):
            counted_roles.append((match.group(1), match.group(2)))
    if len(counted_roles) > 1:
        return ", ".join(f"{count} {role}" for count, role in counted_roles)
    if counted_roles:
        return counted_roles[0][0]
    return None


class _SBBListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.listings: list[dict[str, Any]] = []
        self._listing: dict[str, Any] | None = None
        self._field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and re.search(r"ilanDetay\.aspx(?:\?|$)", attributes.get("href") or "", re.I):
            self._listing = {
                "href": attributes["href"],
                "text": [],
                "fields": {"black": [], "patrol": [], "h5date": []},
            }
        elif tag == "span" and self._listing is not None:
            classes = (attributes.get("class") or "").split()
            self._field = next(
                (name for name in ("black", "patrol", "h5date") if name in classes),
                None,
            )

    def handle_data(self, data: str) -> None:
        if self._listing is None:
            return
        self._listing["text"].append(data)
        if self._field:
            self._listing["fields"][self._field].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._field = None
        elif tag == "a" and self._listing is not None:
            listing = self._listing
            listing["text"] = " ".join(" ".join(listing["text"]).split())
            for name, parts in listing["fields"].items():
                listing[name] = " ".join(" ".join(parts).split())
            del listing["fields"]
            self.listings.append(listing)
            self._listing = None
            self._field = None


def parse_sbb_listing_label(
    label: str,
    *,
    source_url: str = "",
    current_date: date | None = None,
) -> dict[str, Any]:
    """Parse only fields explicitly present in an SBB listing label."""
    current_date = current_date or date.today()
    text = " ".join((label or "").split())
    range_match = _DATE_RANGE.search(text)
    heading = text[:range_match.start()].strip(" ()") if range_match else text

    start_date = end_date = None
    if range_match:
        start_day, start_month, end_day, end_month = range_match.groups()
        start_month_number = _MONTHS.get(normalize_text(start_month))
        end_month_number = _MONTHS.get(normalize_text(end_month))
        if start_month_number and end_month_number:
            start_year = current_date.year
            end_year = start_year + int(end_month_number < start_month_number)
            try:
                start_date = date(start_year, start_month_number, int(start_day))
                end_date = date(end_year, end_month_number, int(end_day))
            except ValueError:
                start_date = end_date = None

    normalized_heading = normalize_text(heading)
    organization = ""
    remainder = heading
    suffix_matches = []
    for suffix in _ORGANIZATION_SUFFIXES:
        normalized_suffix = normalize_text(suffix)
        match = re.search(rf"\b{re.escape(normalized_suffix)}\b", normalized_heading)
        if match:
            suffix_matches.append(match.end())
    if suffix_matches:
        split_at = max(suffix_matches)
        organization = heading[:split_at].strip()
        remainder = heading[split_at:].strip()

    title = remainder or heading
    quota = _extract_quota(title)

    normalized_title = normalize_text(title)
    if "sozlesmeli" in normalized_title:
        employment_type = "Sözleşmeli"
    elif "stajyer" in normalized_title:
        employment_type = "Stajyer"
    elif re.search(r"\bisci\b", normalized_title):
        employment_type = "İşçi"
    elif re.search(r"\bmemur\b", normalized_title):
        employment_type = "Memur"
    else:
        employment_type = "Kaynakta belirtilmedi"

    recruitment_method = detect_recruitment_method(title, title)
    if recruitment_method == "Kurum alımı":
        recruitment_method = "Kaynakta belirtilmedi"

    return {
        "title": title,
        "institution": organization or "Kaynakta bulunamadı",
        "position_title": title or "Kaynakta bulunamadı",
        "city": None,
        "quota": quota,
        "employment_type": employment_type,
        "announcement_date": None,
        "application_start_date": start_date,
        "application_end_date": end_date,
        "recruitment_method": recruitment_method,
        "source_url": source_url,
        "description": text,
    }


def _normalize_listing_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


class SBBSource(BaseJobSource):
    source_name = "SBB Kamu İlanları"
    base_url = "https://kamuilan.sbb.gov.tr/"

    def fetch_listings(self) -> list[dict[str, Any]]:
        final_url, html = fetch_html(self.source_name, self.base_url)
        parser = _SBBListingParser()
        parser.feed(html)

        unique: dict[str, dict[str, Any]] = {}
        for raw in parser.listings:
            detail_url = absolute_url(final_url, raw["href"])
            listing_text = raw["text"]
            structured = bool(raw.get("black") and raw.get("patrol") and raw.get("h5date"))
            if structured:
                label = f"{raw['black']} {raw['patrol']} {raw['h5date']}"
                parsed = parse_sbb_listing_label(label, source_url=detail_url)
                parsed["institution"] = raw["black"]
                parsed["title"] = raw["patrol"]
                parsed["position_title"] = raw["patrol"]
                parsed["description"] = label
            else:
                parsed = parse_sbb_listing_label(listing_text, source_url=detail_url)

            title = parsed["title"]
            institution = parsed["institution"]
            window = " ".join(
                str(value)
                for value in (parsed["application_start_date"], parsed["application_end_date"])
                if value
            )
            unique_key = _normalize_listing_key(f"{institution} {title} {window}")
            item = self.normalize_listing({
                "source_key": "sbb",
                "source_name": self.source_name,
                "source_url": self.base_url,
                "detail_url": detail_url,
                "external_id": content_hash(unique_key),
                "title": title,
                "institution": institution,
                "position_title": parsed["position_title"],
                "city": parsed["city"],
                "quota": parsed["quota"],
                "employment_type": parsed["employment_type"],
                "announcement_date": parsed["announcement_date"],
                "application_start_date": parsed["application_start_date"],
                "application_end_date": parsed["application_end_date"],
                "recruitment_method": parsed["recruitment_method"],
                "description_html": parsed["description"],
                "listing_text": listing_text,
                "listing_only": True,
                "content_hash": content_hash(
                    institution,
                    title,
                    str(parsed["application_start_date"]),
                    str(parsed["application_end_date"]),
                ),
                "metadata": {"list_page": final_url},
            })
            previous = unique.get(unique_key)
            if previous is None or (
                not previous["institution"]
                or previous["institution"] == "Kaynakta bulunamadı"
            ) and institution != "Kaynakta bulunamadı":
                unique[unique_key] = item

        self.pages_checked = 1
        if not unique:
            raise RuntimeError("HTTP 200 yanıtında SBB ilan detay bağlantısı bulunamadı.")
        return list(unique.values())

    def fetch_detail(self, url: str) -> dict[str, Any]:
        final_url, html = fetch_html(self.source_name, url)
        _, text = parse_html_page(html)
        normalized = normalize_text(text)
        if "404" in normalized and "aradiginiz sayfa bulunamadi" in normalized:
            raise RuntimeError(
                f"SBB ilan detay sayfası bulunamadı (HTTP 200 soft-404): {final_url}"
            )
        if len(text) < 100:
            raise RuntimeError(f"SBB ilan detayında ayrıştırılabilir metin yok: {final_url}")
        return {
            "source_text": text,
            "content_hash": content_hash(text),
            "detail_url": final_url,
        }

    @staticmethod
    def external_id(url: str) -> str:
        return external_id(url)

    @staticmethod
    def is_detail_url(url: str) -> bool:
        return bool(
            re.search(
                r"/?ilanDetay\.aspx(?:\?|$)",
                urlsplit(url).path + ("?" if "?" in url else ""),
                re.I,
            )
        )
