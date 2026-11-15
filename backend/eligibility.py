"""Kamu ilanlarını aday profiliyle karşılaştıran temkinli ön eleme motoru.

Kurallar:
- Eğitim, KPSS ve diğer zorunlu şartlar AYRI değerlendirilir; her biri met / not_met / unknown.
- Motor belirli bir bölüme bağlı değildir; adayın bölümü, fakültesi, öğrenim düzeyi ve
  bütün KPSS puan türleri profilden okunur.
- "Tercihen / avantaj / puanlamada" ifadeleri zorunlu şart sayılmaz.
- Vatandaşlık, askerlik, adli sicil, güvenlik soruşturması gibi genel kamu şartları
  `general_conditions` alanında gösterilir; asla `unknown_conditions` listesine girmez.
- Profilde olmayan bilgi uydurulmaz: None = bilinmiyor.
- Sonuç bir ön elemedir; başvuru/atama garantisi vermez.
"""

from datetime import date
import json
import re
import unicodedata

from .kariyerkapisi import _label_values


UNVERIFIED_QUALIFICATION_CODES = {"4531"}
# ÖSYM merkezi yerleştirme "herhangi bir program" nitelik kodları -> öğrenim düzeyi
ANY_PROGRAM_CODES = {"2001": 1, "3001": 2, "4001": 3}
KNOWN_CODE_LABELS = {
    "2001": "Ortaöğretim kurumlarının herhangi bir alanından mezun olmak",
    "3001": "Herhangi bir ön lisans programından mezun olmak",
    "4001": "Herhangi bir lisans programından mezun olmak",
}
LEVEL_NAMES = {0: "ilköğretim", 1: "ortaöğretim (lise)", 2: "ön lisans", 3: "lisans", 4: "yüksek lisans", 5: "doktora"}
# KPSS B grubu puan türleri ile öğrenim düzeyi eşleşmesi
LEVEL_KPSS_TYPE = {1: "P94", 2: "P93", 3: "P3"}

PREFERENCE_MARKERS = (
    "tercihen", "tercih sebebi", "tercih nedeni", "tercih edilir", "tercih edilecek",
    "tercih olunur", "avantaj", "puanlamada", "puanlamaya", "dikkate alin",
    "ek puan", "oncelik verilir", "oncelikli olarak",
)

GENERAL_CONDITIONS = (
    (r"turk vatandasi", "Türk vatandaşı olmak"),
    (r"askerlik", "Askerlik durumu"),
    (r"adli sicil", "Adli sicil kaydı"),
    (r"guvenlik sorusturmasi", "Güvenlik soruşturması (kurum yürütür)"),
    (r"arsiv arastirmasi", "Arşiv araştırması (kurum yürütür)"),
    (r"\b657\b", "657 sayılı Kanun'un genel hükümleri"),
    (r"saglik kurulu|saglik sarti|saglik durumu", "Sağlık şartı"),
)

ACADEMIC_MARKERS = (
    "ogretim elemani", "ogretim uyesi", "ogretim gorevlisi", "arastirma gorevlisi",
    "akademik personel", "profesor", "docent", "doktor ogretim",
    "ars. gor", "ars.gor", "ars gor", "ogr. gor", "ogr.gor", "dr. ogr", "dr.ogr", "ogr. uyesi", "prof. dr", "doc. dr",
)

# İlanlarda sık geçen bölüm/alan kökleri. Adayın bölümü ilanda yokken bunlardan biri
# sayılmışsa ilan başka bölümleri arıyor demektir.
FIELD_TERMS = (
    "bilgisayar", "yazilim", "bilisim", "yapay zeka", "cevre", "insaat", "makine", "elektrik",
    "elektronik", "endustri", "kimya", "harita", "jeoloji", "maden", "metalurji", "malzeme",
    "gida", "biyomedikal", "mekatronik", "otomotiv", "ucak", "gemi", "petrol", "jeofizik",
    "fizik", "nukleer", "tekstil", "ziraat", "orman", "peyzaj", "enerji sistemleri", "mimarlik",
    "sehir ve bolge planlama", "hukuk", "iktisat", "isletme", "maliye", "ekonomi", "ekonometri",
    "kamu yonetimi", "siyaset bilimi", "siyasal bilgiler", "uluslararasi iliskiler",
    "calisma ekonomisi", "muhasebe", "bankacilik", "kutuphanecilik", "bilgi ve belge",
    "matematik", "istatistik", "biyoloji", "psikoloji", "sosyoloji", "sosyal hizmet",
    "veteriner", "eczacilik", "hemsirelik", "ebelik", "fizyoterapi", "beslenme", "diyetetik",
    "iletisim", "gazetecilik", "halkla iliskiler", "tip fakultesi", "dis hekimligi", "tarih",
    "cografya", "arkeoloji", "sanat tarihi", "ilahiyat", "turk dili", "edebiyat", "mutercim",
    "tercumanlik", "ogretmenlig", "egitim fakultesi", "iktisadi ve idari bilimler", "iibf",
    "spor bilimleri", "beden egitimi", "turizm", "lojistik", "is sagligi", "acil yardim",
    "cocuk gelisimi", "adalet", "buro yonetimi", "laborant", "anestezi", "ilk ve acil",
)
# Aynı "tür" sözcüğünü paylaşan bölüm listeleri: "Bilgisayar, Yazılım ve Elektronik Mühendisliği"
DEPARTMENT_TYPE_WORDS = ("muhendis", "ogretmen", "tekniker", "teknisyen", "teknoloji", "bilimleri", "bilimi")
# Birbirine yakın sayılan alanlar: ilan yalnızca yakın alanı sayıyorsa sonuç "doğrulanmalı" olur.
RELATED_FIELDS = (
    {"bilgisayar", "yazilim", "bilisim", "yapay zeka"},
    {"elektrik", "elektronik"},
    {"iktisat", "ekonomi", "ekonometri"},
    {"metalurji", "malzeme"},
    {"harita", "jeoloji", "jeofizik"},
)
# Unvandan anlaşılan meslekler (ilan metni okunamadığında başlık/pozisyon üzerinden ön eleme)
PROFESSION_TERMS = {
    "avukat": "Avukat", "psikolog": "Psikolog", "hemsire": "Hemşire", "ebe": "Ebe", "tabip": "Tabip",
    "veteriner": "Veteriner hekim", "eczaci": "Eczacı", "ogretmen": "Öğretmen", "mimar": "Mimar",
    "kutuphaneci": "Kütüphaneci", "sosyolog": "Sosyolog", "diyetisyen": "Diyetisyen",
    "fizyoterapist": "Fizyoterapist", "sosyal calismaci": "Sosyal çalışmacı", "biyolog": "Biyolog",
    "kimyager": "Kimyager", "istatistikci": "İstatistikçi", "imam": "İmam", "dis hekimi": "Diş hekimi",
    "saglik teknikeri": "Sağlık teknikeri", "laborant": "Laborant", "arkeolog": "Arkeolog",
    "sehir plancisi": "Şehir plancısı", "cocuk gelisimci": "Çocuk gelişimci",
}


def normalize_text(value):
    value = (value or "").translate(str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"}))
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _job_value(job, key, default=""):
    if isinstance(job, dict):
        return job.get(key, default)
    return getattr(job, key, default)


_LIST_MARKER = re.compile(r"^\s*(?:[a-zçğıöşü]{1,2}[\)\.]|\d{1,2}[\)\.\-]|[-•–▪*])\s+", re.I)


def reflow_text(text):
    """PDF'den gelen satır sonu kırılmalarını cümle bütünlüğü için birleştirir."""
    lines = [line.rstrip() for line in (text or "").splitlines()]
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        previous = out[-1] if out else ""
        if (
            previous
            and len(previous) >= 45
            and not re.search(r"[.;:!?]$", previous)
            and not _LIST_MARKER.match(stripped)
            and not re.match(r"^[^:：]{2,40}[:：]\s*\S", stripped)
        ):
            out[-1] = f"{previous} {stripped}"
        else:
            out.append(stripped)
    return "\n".join(out)


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text or "") if part.strip()]


def _is_preference(normalized_sentence):
    return any(marker in normalized_sentence for marker in PREFERENCE_MARKERS)


def _has_term(text, term):
    return re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text) is not None


def _extract_codes(job, description):
    raw = set(re.findall(r"(?<!\d)(\d{4})(?!\d)", str(_job_value(job, "qualification_codes", "") or "")))
    for line in description.splitlines():
        if "nitelik kod" in normalize_text(line):
            raw.update(re.findall(r"(?<!\d)(\d{4})(?!\d)", line))
    return sorted(code for code in raw if not 1900 <= int(code) <= 2100)


_KPSS_TYPE = re.compile(r"(?:kpss\s*-?\s*|(?<![a-z0-9]))p\s?-?(\d{1,3})(?!\d)")


def _extract_kpss_types(job, sentences):
    stored = normalize_text(str(_job_value(job, "kpss_score_type", "") or ""))
    found = [f"P{int(number)}" for number in _KPSS_TYPE.findall(stored)]
    if found and _job_value(job, "position_specific", False):
        # Kadro satırının kendi puan türü varsa diğer satırların türleri karışmasın.
        sentences = []
    for _, normalized in sentences:
        if "kpss" in normalized:
            found.extend(f"P{int(number)}" for number in _KPSS_TYPE.findall(normalized))
    valid = {value for value in found if 1 <= int(value[1:]) <= 130}
    return sorted(valid, key=lambda value: int(value[1:]))


_MIN_SCORE_PATTERNS = (
    re.compile(r"(?:en az|asgari|taban)\s*(?<!\d)(\d{2,3}(?:[.,]\d+)?)(?!\s*(?:yil|yas|ay\b|gun|kisi|kat))"),
    re.compile(r"(?<![\d.,/])(\d{2,3}(?:[.,]\d+)?)\s*(?:\([^)]{0,25}\)\s*)?(?:puan\s*)?(?:ve\s+)?(?:uzeri|uzerinde|ustu|ustunde|daha (?:fazla|yukari))"),
)


def _extract_kpss_minimum(job, sentences):
    stored = _job_value(job, "kpss_min_score", None)
    if stored is not None:
        return float(stored)
    for _, normalized in sentences:
        if "kpss" not in normalized:
            continue
        for pattern in _MIN_SCORE_PATTERNS:
            for match in pattern.finditer(normalized):
                value = float(match.group(1).replace(",", "."))
                if 40 <= value <= 100:
                    return value
    return None


def _field_from_description(description, key):
    parsed = _label_values(description)
    if key in parsed:
        return parsed[key]
    labels = {
        "quota": ("Kontenjan", "Adet", "Kişi Sayısı"),
        "position": ("Pozisyon / unvan", "Pozisyon", "Ünvan", "Unvan"),
        "start_date": ("Başvuru başlangıcı", "Başvuru Başlangıç Tarihi"),
    }.get(key, ())
    for line in description.splitlines():
        for label in labels:
            match = re.match(rf"^\s*{re.escape(label)}\s*[:：]\s*(.*)$", line, re.I)
            if match and match.group(1).strip():
                return match.group(1).strip()
    return ""


def _has_zero_score_fallback(description):
    normalized = normalize_text(description)
    return (
        "yabanci dil puani olmayan" in normalized
        and "0 (sifir)" in normalized
        and "olarak degerlendirilecektir" in normalized
    )


SPECIAL_GROUPS = (
    ("eski hukumlu", "eski hükümlü / terörle mücadelede yaralanan"),
    ("engelli", "engelli (EKPSS)"),
)


def _special_group(title: str, description: str):
    """Yalnızca belirli statüdeki adaylara açık ilanları tanır."""
    head = normalize_text(f"{title} {description[:500]}")
    title_norm = normalize_text(title)
    for key, label in SPECIAL_GROUPS:
        if key in title_norm or (key == "engelli" and "ekpss" in title_norm) or re.search(
            rf"{key}[^.]{{0,160}}\balim", head
        ):
            return key, label
    return None


def is_academic_listing(title: str, position: str = "") -> bool:
    text = normalize_text(f"{title or ''} {position or ''}")
    return any(marker in text for marker in ACADEMIC_MARKERS)


def detect_recruitment_method(title: str, description: str) -> str:
    """İlan metnini esas alarak alım yöntemini tespit eder."""
    text = normalize_text(f"{title or ''} {description or ''}")

    if is_academic_listing(title):
        return "Akademik personel alımı"
    if re.search(r"yazili\s+(?:ve(?:ya)?\s+)?sozlu\s+sinav\s+yapil(?:maksizin|madan)|sinavsiz\s+olarak|kpss\s*\(?b\)?\s+grubu\s+puan\s+siralamasi\s+esas", text):
        return "KPSS puan sıralaması"
    if re.search(r"kpss\s+puan\s+siralamasi.*sozlu\s+sinav|sozlu\s+sinav\s+sonucuna\s+gore|kpss.*puani.*esas\s+alin.*sozlu\s+sinav", text):
        return "KPSS puan sıralaması + sözlü sınav"
    if re.search(r"giris\s+sinavi|yarisma\s+sinavi|uzman\s+yardimciligi\s+giris|sozlesmeli\s+muhendis\s+ve\s+tekniker\s+giris", text):
        return "Kurum Giriş Sınavı"
    if re.search(r"kpss\s+merkezi\s+yerlestirme|osym\s+yerlestirme", text):
        return "KPSS merkezi yerleştirme"
    if re.search(r"sozlesmeli\s+bilisim\s+personeli", text):
        return "Sözleşmeli bilişim personeli alımı"
    if re.search(r"isci\s+alim|surekli\s+isci|\bisci\b", text):
        return "İşçi alımı"
    if re.search(r"kpss\s+puaniyla|kpss\s+puani\s+esas\s+alin|kpss\s+puan\s+siralamasi", text):
        return "KPSS puan sıralaması"
    return "Kurum alımı"


def detect_application_status(start_date: date | None, end_date: date | None, today: date | None = None) -> str:
    """Eldeki tarihlerin desteklediği başvuru durumunu döndürür."""
    if today is None:
        today = date.today()
    if end_date and end_date < today:
        return "Başvuru Sona Erdi"
    if start_date and start_date > today:
        return "Başvuru Başlamadı"
    if end_date:
        # Son başvuru tarihi geçmediyse ve başlangıç ileri bir tarih değilse başvuru açıktır.
        return "Başvuru Açık"
    return "Tarih belirtilmemiş"


# ----------------------------------------------------------------------------
# Aday tarafı: öğrenim düzeyi, bölüm ve fakülte desenleri
# ----------------------------------------------------------------------------

def degree_level(degree: str) -> int | None:
    text = normalize_text(degree)
    if not text.strip():
        return None
    if "doktora" in text:
        return 5
    if "yuksek lisans" in text or "master" in text:
        return 4
    if "on lisans" in text or "onlisans" in text or "meslek yuksek" in text:
        return 2
    if "lisans" in text or "universite" in text:
        return 3
    if "lise" in text or "ortaogretim" in text:
        return 1
    if "ilkogretim" in text or "ortaokul" in text or "ilkokul" in text:
        return 0
    return None


def _department_names(candidate) -> list[str]:
    names = [candidate.get("department", "")]
    names.extend(re.split(r"[,;\n]", str(candidate.get("department_aliases") or "")))
    cleaned = []
    for name in names:
        value = re.sub(r"\s+", " ", normalize_text(name)).strip()
        value = re.sub(r"\s+(?:bolumu|programi|anabilim dali)$", "", value)
        if len(value) >= 3 and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _department_patterns(names: list[str]) -> list[re.Pattern]:
    patterns = []
    for name in names:
        words = name.split()
        type_index = next(
            (index for index, word in enumerate(words) if index and word.startswith(DEPARTMENT_TYPE_WORDS)),
            None,
        )
        if type_index is not None:
            stem = r"\s+".join(re.escape(word) for word in words[:type_index])
            type_word = next(root for root in DEPARTMENT_TYPE_WORDS if words[type_index].startswith(root))
            # "bilgisayar mühendisliği", "bilgisayar mühendisi" ve
            # "bilgisayar, yazılım ve elektronik mühendisliği" biçimlerini yakalar.
            patterns.append(re.compile(
                rf"(?<![a-z]){stem}(?:\s+{type_word}|\s*(?:[,/]|\s+ve(?:ya)?\s)[^.;:\n]{{0,140}}?{type_word})"
            ))
        else:
            patterns.append(re.compile(rf"(?<![a-z]){re.escape(name)}(?![a-z])"))
    return patterns


def _faculty_stems(candidate) -> list[str]:
    stems = []
    for name in re.split(r"[,;\n]", str(candidate.get("faculty") or "")):
        value = re.sub(r"\s+", " ", normalize_text(name)).strip()
        value = re.sub(r"\s+fakultesi$|\s+fakulte$|\s+yuksekokulu$", "", value)
        if len(value) >= 3:
            stems.append(value)
            if value == "iktisadi ve idari bilimler":
                stems.append("iibf")
    return stems


# ----------------------------------------------------------------------------
# Eğitim şartı kontrolü
# ----------------------------------------------------------------------------

def _education_evidence(job, description, position_specific=False):
    evidence, seen = [], []

    def add(text):
        cleaned = " ".join(text.split()).strip()
        key = normalize_text(cleaned)
        if not cleaned or any(key in other or other in key for other in seen):
            return
        seen.append(key)
        evidence.append(cleaned)

    stored = str(_job_value(job, "education_requirement", "") or "").strip()
    if "ilan metninde dort yillik fakult" in normalize_text(stored):
        stored = ""
    if stored:
        add(stored)
        if position_specific:
            # Kadro satırında unvan da bölüm bilgisi taşıyabilir: "Uzman (Mühendislik programları)".
            add(str(_job_value(job, "position", "") or ""))
            return evidence

    for line in description.splitlines():
        label = re.match(
            r"\s*(?:mezuniyet bolumleri|mezun olunacak bolumler|bolum sarti|kabul edilen bolumler|kabul edilen gruplar|aranan bolumler|ogrenim durumu|ogrenim dallari)\s*[:：]\s*(.+)",
            normalize_text(line),
        )
        if label and ":" in line:
            add(line.split(":", 1)[1])

    for sentence in _sentences(reflow_text(description)):
        normalized = normalize_text(sentence)
        if "mezun" not in normalized and not (
            "fakulte" in normalized and re.search(r"bolum|program", normalized)
        ):
            continue
        if any(skip in normalized for skip in ("mezun olunan", "mezuniyetinden sonra", "mezuniyet sonrasi", "mezuniyet tarih")):
            continue
        if re.search(r"belge|diploma|transkript|e-devlet|barkod|yukle", normalized) and not re.search(
            r"mezun ol(?:mak|masi|malari|mus olmak|anlar)|mezunu ol", normalized
        ):
            continue
        if _is_preference(normalized) or len(sentence) > 1500:
            continue
        add(sentence)
    return evidence


def _required_levels(text):
    levels = set()
    if re.search(r"on\s?lisans|meslek yuksekokul", text):
        levels.add(2)
    if re.search(r"(?<!on )(?<!on)(?<!yuksek )lisans(?! ?ustu)", text) or re.search(r"dort yillik|4 yillik|fakulte", text):
        levels.add(3)
    if re.search(r"ortaogretim|lise(?:\s|$|,)|lise ve dengi|lise veya dengi", text):
        levels.add(1)
    if re.search(r"yuksek lisans(?: veya doktora)? (?:mezunu|yapmis|derecesine)", text):
        levels.add(4)
    return levels


def _assess_education(candidate, evidence, codes, title="", position=""):
    """(status, açıklama) döndürür. status: met | not_met | unknown."""
    level = degree_level(candidate.get("degree", ""))
    names = _department_names(candidate)
    department_label = candidate.get("department") or "bölümünüz"
    text = re.sub(r"\s+", " ", normalize_text(" ".join(evidence)))

    # 1. "Herhangi bir program" nitelik kodları
    for code, required in ANY_PROGRAM_CODES.items():
        if code in codes:
            label = KNOWN_CODE_LABELS[code]
            if level is None:
                return "unknown", f"{code} kodu ({label}); profilde öğrenim düzeyi girilmemiş."
            if level == required or (required == 3 and level > 3):
                return "met", f"{code} kodu ({label}); öğrenim düzeyiniz bu şartı karşılıyor."
            return "not_met", f"{code} kodu ({label}); öğrenim düzeyiniz {LEVEL_NAMES.get(level, 'farklı')}."

    if not text.strip():
        return _assess_from_title(names, department_label, title, position) or (
            "unknown", "İlan metninde öğrenim/bölüm şartı bulunamadı; resmî ilandan doğrulanmalı."
        )

    # 2. Öğrenim düzeyi alt sınırı
    levels = _required_levels(text)
    if levels and level is not None and level < min(levels):
        return "not_met", (
            f"İlan en az {LEVEL_NAMES[min(levels)]} mezuniyeti istiyor; "
            f"profilinizdeki öğrenim düzeyi {LEVEL_NAMES.get(level, 'daha düşük')}."
        )

    # 3. Adayın bölümü ilanda açıkça geçiyor mu?
    if names and any(pattern.search(text) for pattern in _department_patterns(names)):
        return "met", f"İlanda kabul edilen bölümler arasında {department_label} açıkça yer alıyor."

    named = [
        term for term in FIELD_TERMS
        if _has_term(text, term) and not any(term in name for name in names)
    ]
    restricts_department = bool(re.search(r"bolum|program|dallar|alanlar", text))

    # 4. Fakülte düzeyinde kabul
    faculty_stems = _faculty_stems(candidate)
    faculty_hit = next((stem for stem in faculty_stems if _has_term(text, stem) and "fakulte" in text or stem == "iibf" and "iibf" in text), None)
    generic_engineering = re.search(r"muhendislik\s+(?:fakulte|bolum|program|alan|dallar)|tum muhendislik|butun muhendislik", text)
    candidate_is_engineer = any("muhendis" in name for name in names) or any("muhendis" in stem for stem in faculty_stems)
    if faculty_hit or (generic_engineering and candidate_is_engineer):
        specific = [term for term in named if term not in (faculty_hit or "") and term not in ("iktisadi ve idari bilimler",)]
        if restricts_department and specific and not generic_engineering:
            return "not_met", (
                "İlan fakültenizin yalnızca belirli bölümlerini kabul ediyor "
                f"({_format_terms(specific)}); {department_label} listede yok."
            )
        if generic_engineering and candidate_is_engineer and not faculty_hit:
            return "met", "İlan bölüm kısıtı olmaksızın mühendislik fakültesi mezunlarını kabul ediyor."
        return "met", "İlan fakültenizin mezunlarını kabul ediyor."

    # 5. Herhangi bir program
    any_program = re.search(
        r"herhangi bir (?:lisans|on lisans|onlisans|ortaogretim|bolum|program|yuksekogretim)|"
        r"(?:lisans|on lisans|onlisans|lise|ortaogretim)(?: duzeyinde)? (?:egitim veren )?(?:herhangi|tum|butun)",
        text,
    )
    plain_level = (
        levels and not named and not restricts_department and "fakulte" not in text
        and re.search(
            r"(?:lisans|lise|ortaogretim|yuksekogretim)\w*(?: ve(?:ya)? dengi(?: okul)?)? (?:mezunu olmak|derecesine sahip olmak|duzeyinde (?:ogrenim|egitim))",
            text,
        )
    )
    if (any_program and not named or plain_level) and level is not None:
        required = min(levels) if levels else level
        if level >= required:
            return "met", "İlan belirli bir bölüm aramıyor; öğrenim düzeyiniz yeterli."

    # 6. Başka bölümler sayılmış, adayınki yok
    if named:
        if not names:
            return "unknown", "İlan belirli bölümler arıyor; profilde bölüm girilmemiş."
        candidate_terms = {term for term in FIELD_TERMS if any(term in name for name in names)}
        if any(candidate_terms & family and set(named) <= family for family in RELATED_FIELDS):
            return "unknown", (
                f"İlan yakın bir alanı sayıyor ({_format_terms(named)}); {department_label} açıkça yazmıyor. "
                "Denklik için resmî ilandan doğrulayın veya profilinize eşdeğer bölüm ekleyin."
            )
        return "not_met", f"İlanda aranan alanlar: {_format_terms(named)}. {department_label} bu listede yer almıyor."

    if any(phrase in text for phrase in ("tablo", "ekli liste", "ekte yer alan", "asagida belirtilen")):
        return "unknown", "Kabul edilen bölümler ilanın tablosunda/ekinde yer alıyor; resmî ilandan doğrulanmalı."
    return _assess_from_title(names, department_label, title, position) or (
        "unknown", "Bölüm/mezuniyet şartı profilinizle kesin eşleştirilemedi; resmî ilandan doğrulanmalı."
    )


def _assess_from_title(names, department_label, title, position):
    """Metinden sonuç çıkmadığında ilan başlığındaki/pozisyondaki unvanı kullanır."""
    text = re.sub(r"\s+", " ", normalize_text(f"{position} {title}"))
    if names and any(pattern.search(text) for pattern in _department_patterns(names)):
        return "unknown", (
            f"İlan başlığındaki unvan {department_label} ile örtüşüyor; "
            "öğrenim şartının ayrıntısı resmî ilandan doğrulanmalı."
        )
    if not names:
        return None
    professions = [label for term, label in PROFESSION_TERMS.items() if _has_term(text, term)]
    fields = [
        term for term in FIELD_TERMS
        if not any(term in name for name in names)
        and re.search(rf"(?<![a-z]){re.escape(term)}\s+(?:muhendis|tekniker|teknisyen)", text)
    ]
    if professions or fields:
        wanted = ", ".join(professions + [f"{_TERM_LABELS.get(term, term.title())} Mühendisliği/Teknikerliği" for term in fields])
        return "not_met", f"İlan {wanted} unvanı için; {department_label} bu unvanla örtüşmüyor."
    return None


_TERM_LABELS = {
    "yazilim": "Yazılım", "bilisim": "Bilişim", "cevre": "Çevre", "insaat": "İnşaat", "endustri": "Endüstri",
    "gida": "Gıda", "ucak": "Uçak", "nukleer": "Nükleer", "isletme": "İşletme", "kamu yonetimi": "Kamu Yönetimi",
    "siyaset bilimi": "Siyaset Bilimi", "siyasal bilgiler": "Siyasal Bilgiler",
    "uluslararasi iliskiler": "Uluslararası İlişkiler", "iktisadi ve idari bilimler": "İktisadi ve İdari Bilimler",
    "kutuphanecilik": "Kütüphanecilik", "hemsirelik": "Hemşirelik", "ogretmenlig": "Öğretmenlik",
    "iletisim": "İletişim", "tip fakultesi": "Tıp", "dis hekimligi": "Diş Hekimliği", "eczacilik": "Eczacılık",
    "mimarlik": "Mimarlık", "egitim fakultesi": "Eğitim Fakültesi", "cografya": "Coğrafya",
    "sehir ve bolge planlama": "Şehir ve Bölge Planlama", "muhasebe": "Muhasebe", "bankacilik": "Bankacılık",
    "calisma ekonomisi": "Çalışma Ekonomisi", "yapay zeka": "Yapay Zekâ", "is sagligi": "İş Sağlığı",
    "cocuk gelisimi": "Çocuk Gelişimi", "buro yonetimi": "Büro Yönetimi", "turk dili": "Türk Dili",
    "sanat tarihi": "Sanat Tarihi", "halkla iliskiler": "Halkla İlişkiler", "beden egitimi": "Beden Eğitimi",
}


def _format_terms(terms):
    labels = [_TERM_LABELS.get(term, term.title()) for term in terms[:8]]
    return ", ".join(labels) + (" …" if len(terms) > 8 else "")


# ----------------------------------------------------------------------------
# Ana sınıflandırma
# ----------------------------------------------------------------------------

def classify_public_job(job, candidate):
    """Kategori, gerekçe ve şart bazında değerlendirme döndürür."""
    title = str(_job_value(job, "title", "") or "")
    position = str(_job_value(job, "position", "") or "")
    description = str(_job_value(job, "description", "") or "")
    position_specific = bool(_job_value(job, "position_specific", False))
    codes = _extract_codes(job, description)
    education_evidence = _education_evidence(job, description, position_specific)
    flowed = reflow_text(description)
    normalized_text = normalize_text("\n".join((title, position, " ".join(codes), description)))
    sentences = [(sentence, normalize_text(sentence)) for sentence in _sentences(flowed)]
    position_norm = normalize_text(f"{title} {position}")

    def applies_to_position(normalized_sentence):
        # "Ziraat Mühendisi pozisyonları için ..." gibi cümleler yalnızca o pozisyonu bağlar.
        scoped = re.match(
            r"^[\d.\-\)\s]*([a-z][a-z\s/-]{2,60}?(?:muhendisi|teknikeri|teknisyeni|uzmani|personeli|memuru|programcisi|avukat))"
            r"\s+(?:pozisyon\w*\s+|kadro\w*\s+|unvan\w*\s+)?icin\b",
            normalized_sentence,
        )
        return not scoped or scoped.group(1).strip() in position_norm

    mandatory = [
        (sentence, normalized) for sentence, normalized in sentences
        if not _is_preference(normalized) and applies_to_position(normalized)
    ]

    reasons, unknowns, mismatches, requirements = [], [], [], []

    def add(name, status, detail):
        requirements.append({"name": name, "status": status, "detail": detail})
        {"met": reasons, "not_met": mismatches, "unknown": unknowns}[status].append(detail)

    academic = is_academic_listing(title, position)
    special = _special_group(title, description)
    has_detail = len(description.strip()) >= 250 or bool(education_evidence) or bool(codes)

    # ---- 0. Özel statü ilanları (engelli, eski hükümlü vb.) ---------------
    if special:
        have = normalize_text(str(candidate.get("special_status") or ""))
        key, label = special
        if key in have:
            add("Özel statü", "met", f"İlan {label} adaylar için; profilinizde bu statü belirtilmiş.")
        else:
            add("Özel statü", "not_met", f"Bu ilan yalnızca {label} adaylar içindir.")

    # ---- 1. Eğitim -------------------------------------------------------
    if academic:
        education_status = "not_met"
        education_detail = (
            "Akademik kadro ilanı (öğretim elemanı); KPSS ile alım yapılmaz, "
            "ALES ve yabancı dil şartları aranır."
        )
        add("Kapsam", education_status, education_detail)
    else:
        education_status, education_detail = _assess_education(candidate, education_evidence, codes, title, position)
        if not has_detail and education_status == "unknown":
            education_detail = "İlanın ayrıntılı şartları henüz okunamadı; yalnızca liste bilgisi var."
        add("Eğitim", education_status, education_detail)

    for code in codes:
        if code in ANY_PROGRAM_CODES:
            continue
        if code in UNVERIFIED_QUALIFICATION_CODES:
            add(f"Nitelik kodu {code}", "unknown", f"{code} nitelik kodunun güncel resmî tanımı kılavuzdan doğrulanmalıdır.")
        elif education_status != "met":
            add(f"Nitelik kodu {code}", "unknown", f"{code} nitelik kodunun tanımı kılavuzdan doğrulanmalıdır.")

    # ---- 2. KPSS ---------------------------------------------------------
    kpss_sentences = sentences + [(title, normalize_text(title))]
    kpss_types = _extract_kpss_types(job, kpss_sentences)
    minimum = _extract_kpss_minimum(job, kpss_sentences)
    scores = {str(key).upper(): float(value) for key, value in (candidate.get("kpss_scores") or {}).items()}
    candidate_kpss_type = str(candidate.get("kpss_score_type", "") or "").upper()
    candidate_kpss_score = candidate.get("kpss_score")
    if candidate_kpss_type and candidate_kpss_score is not None:
        scores.setdefault(candidate_kpss_type, float(candidate_kpss_score))

    kpss_status = "unknown"
    mentions_kpss = "kpss" in normalized_text
    if not academic and (kpss_types or minimum is not None):
        usable = [kind for kind in kpss_types if kind in scores]
        if not scores:
            add("KPSS", "unknown", "Profilde KPSS puanı girilmemiş.")
        elif kpss_types and not usable:
            kpss_status = "not_met"
            add("KPSS", "not_met", (
                f"İlan {'/'.join(kpss_types)} puan türünü istiyor; profilinizde bu türde puan yok "
                f"(kayıtlı: {', '.join(sorted(scores))})."
            ))
        elif not kpss_types:
            add("KPSS", "unknown", (
                f"İlan en az {minimum:g} KPSS puanı istiyor ancak puan türü metinden okunamadı; resmî ilandan doğrulanmalı."
            ))
        else:
            used = max(usable, key=lambda kind: scores[kind])
            score = scores[used]
            candidate_kpss_type, candidate_kpss_score = used, score
            if minimum is not None and score < minimum:
                kpss_status = "not_met"
                add("KPSS", "not_met", f"{used} puanınız {score:.2f}; ilanın taban puanı {minimum:g}.")
            elif minimum is not None:
                kpss_status = "met"
                add("KPSS", "met", f"{used} puanınız {score:.2f}; taban puan {minimum:g} şartını karşılıyor.")
            else:
                kpss_status = "met"
                add("KPSS", "met", f"{used} puanınız {score:.2f}; ilanın puan türüyle eşleşiyor, taban puan belirtilmemiş.")
    elif not academic and mentions_kpss:
        add("KPSS", "unknown", "İlanda KPSS şartı var ancak puan türü/taban puan metinden okunamadı; resmî ilandan doğrulanmalı.")

    if not academic:
        _assess_other_requirements(candidate, description, mandatory, normalized_text, add)

    general = [label for pattern, label in GENERAL_CONDITIONS if re.search(pattern, normalized_text)]
    unknowns = list(dict.fromkeys(unknowns))
    mismatches = list(dict.fromkeys(mismatches))
    reasons = list(dict.fromkeys(reasons))

    if mismatches:
        category = "UYGUN DEĞİL"
        reason = " | ".join(mismatches)
    elif unknowns:
        category = "POTANSİYEL OLARAK UYGUN"
        core = [item["detail"] for item in requirements if item["status"] == "met" and item["name"] in ("Eğitim", "KPSS")]
        prefix = f"{' '.join(core)} " if core else ""
        reason = f"{prefix}Doğrulanması gerekenler: {' '.join(unknowns)}"
    else:
        category = "UYGUN"
        reason = " ".join(reasons) or "İlandaki ayrıştırılabilen tüm zorunlu şartlar profilinizle uyumlu."

    status_label = {"met": "KABUL EDİLİYOR", "not_met": "KABUL EDİLMİYOR", "unknown": "BELİRSİZ"}[education_status]
    return {
        "category": category,
        "reason": reason,
        "unknown_conditions": unknowns,
        "met_conditions": reasons,
        "failed_conditions": mismatches,
        "requirements": requirements,
        "general_conditions": general,
        "kind": "academic" if academic else "standard",
        "data_quality": "full" if has_detail or academic else "listing_only",
        "education": {
            "requirement": " ".join(education_evidence),
            "label": status_label,
            "computer_engineering": status_label,  # eski istemcilerle uyumluluk
            "status": education_status,
            "basis": education_detail,
        },
        "kpss": {
            "score_types": kpss_types,
            "minimum_score": minimum,
            "candidate_score_type": candidate_kpss_type,
            "candidate_score": candidate_kpss_score,
            "status": kpss_status,
        },
        "qualification_codes": codes,
        "position": _field_from_description(description, "position") or position or title,
        "quota": _field_from_description(description, "quota"),
        "start_date": _field_from_description(description, "start_date"),
    }


def _assess_other_requirements(candidate, description, mandatory, normalized_text, add):
    # ---- YDS / yabancı dil -----------------------------------------------
    yds_minimum, yds_required = None, False
    for _, normalized in mandatory:
        if not re.search(r"\b(?:yds|e-yds|yokdil|yabanci dil|ingilizce|almanca|fransizca|arapca|rusca)\b", normalized):
            continue
        minimum_match = re.search(r"(?:en az|asgari)\s*(\d{2,3}(?:[.,]\d+)?)", normalized)
        if minimum_match and re.search(r"puan|duzey|seviye", normalized):
            yds_minimum = min(yds_minimum or 999.0, float(minimum_match.group(1).replace(",", ".")))
            yds_required = True
        elif any(term in normalized for term in ("puan almak", "puan almis olmak", "belgeye sahip olmak")):
            yds_required = True
            if "c duzeyinde" in normalized or "c seviye" in normalized:
                yds_minimum = 70.0
    if yds_required and (yds_minimum is not None or not _has_zero_score_fallback(description)):
        yds = candidate.get("yds_score")
        if yds is None:
            detail = (
                f"İlan en az {yds_minimum:g} YDS/yabancı dil puanı istiyor; profilde dil puanı yok."
                if yds_minimum else "YDS/yabancı dil şartı var; profilde dil puanı yok."
            )
            add("YDS", "unknown", detail)
        elif yds_minimum is not None and float(yds) < yds_minimum:
            add("YDS", "not_met", f"YDS puanınız {float(yds):g}; ilan en az {yds_minimum:g} istiyor.")
        else:
            add("YDS", "met", f"YDS puanınız ({float(yds):g}) ilanın şartını karşılıyor.")

    # ---- Yaş -------------------------------------------------------------
    age_limit, age_required = None, False
    for _, normalized in mandatory:
        match = re.search(
            r"(\d{2})\s*(?:\([^)]{0,20}\)\s*)?yas\w*\s+(?:gununu\s+)?(?:doldurmamis|bitirmemis|gun almamis|asmamis|gecmemis)",
            normalized,
        )
        if match:
            age_limit, age_required = int(match.group(1)), True
        elif "yas siniri" in normalized or "ust yas" in normalized:
            age_required = True
    if age_required:
        age = candidate.get("age")
        if age is None:
            add("Yaş", "unknown", f"İlanda {f'{age_limit} ' if age_limit else ''}yaş sınırı var; profilde yaş girilmemiş.")
        elif age_limit is not None and int(age) >= age_limit:
            add("Yaş", "not_met", f"{int(age)} yaşındasınız; ilan {age_limit} yaşını doldurmamış olmayı istiyor.")
        else:
            add("Yaş", "met", f"{int(age)} yaşındasınız; yaş şartı karşılanıyor (ilandaki esas tarihi kontrol edin).")

    # ---- Deneyim ---------------------------------------------------------
    experience_years, experience_required = None, False
    for _, normalized in mandatory:
        if not any(term in normalized for term in ("deneyim", "tecrube", "calismis olmak")):
            continue
        years = re.search(r"en az\s+(\d+)\s*(?:\([^)]*\)\s*)?yil", normalized)
        if years:
            experience_years, experience_required = min(experience_years or 99, int(years.group(1))), True
        elif re.search(r"sahip olmak|aranir|zorunlu|bulunmak", normalized):
            experience_required = True
    if experience_required:
        have = candidate.get("experience_years")
        if have is None:
            add("Deneyim", "unknown", f"İlan {f'en az {experience_years} yıl ' if experience_years else ''}mesleki deneyim istiyor; profilde deneyim süresi yok.")
        elif experience_years is not None and float(have) < experience_years:
            add("Deneyim", "not_met", f"Deneyiminiz {float(have):g} yıl; ilan en az {experience_years} yıl istiyor.")
        else:
            add("Deneyim", "met", f"{float(have):g} yıllık deneyiminiz ilanın şartını karşılıyor.")

    # ---- Sürücü belgesi --------------------------------------------------
    if any(re.search(r"surucu belgesi|ehliyet", n) and re.search(r"zorunlu|sahip olmak|aranir|gereklidir", n) for _, n in mandatory):
        have = candidate.get("driver_license")
        if have is None:
            add("Sürücü belgesi", "unknown", "Sürücü belgesi şartı var; profilde ehliyet bilgisi yok.")
        elif have:
            add("Sürücü belgesi", "met", "Sürücü belgesi şartı karşılanıyor.")
        else:
            add("Sürücü belgesi", "not_met", "İlan sürücü belgesi istiyor; sürücü belgeniz yok.")

    # ---- Sertifika -------------------------------------------------------
    cert_sentences = [
        n for _, n in mandatory
        if "sertifika" in n and re.search(r"zorunlu|sahip olmak|belgelemek|ibraz|en az birine", n)
    ]
    if cert_sentences:
        owned = [normalize_text(c).strip() for c in re.split(r"[,;\n]", str(candidate.get("certificates") or "")) if c.strip()]
        if not owned:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı var; profilde sertifika yok.")
        elif any(cert in sentence for cert in owned for sentence in cert_sentences):
            add("Sertifika", "met", "Profildeki sertifika ilanın istediğiyle eşleşiyor.")
        else:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı var; profildeki sertifikalarla eşleşme resmî ilandan doğrulanmalı.")

    # ---- Programlama dili belgeleme --------------------------------------
    if re.search(r"programlama dillerinden en az (?:iki|ikisini|2)", normalized_text):
        if not candidate.get("programming_language_evidence"):
            add("Programlama dilleri", "unknown", "En az iki programlama dilini bildiğini belgeleme şartı var; profilde kanıt yok.")
        else:
            add("Programlama dilleri", "met", "Profilde programlama dili kanıtı bulunuyor.")

    # ---- Cinsiyet (kadro satırında belirtilmişse) --------------------------
    gender_match = re.search(r"cinsiyet\w*\s*[:：]?\s*(erkek|kadin)(?!\s*/|\s*(?:ve|veya)\s)", normalized_text)
    if gender_match:
        wanted = gender_match.group(1)
        have = normalize_text(str(candidate.get("gender") or "")).strip()
        label = "Erkek" if wanted == "erkek" else "Kadın"
        if not have:
            add("Cinsiyet", "unknown", f"Kadro {label} adaylar için; profilde cinsiyet belirtilmemiş.")
        elif have == wanted:
            add("Cinsiyet", "met", f"Kadro {label} adaylar için; profilinizle uyumlu.")
        else:
            add("Cinsiyet", "not_met", f"Kadro yalnızca {label} adaylar için.")

    # ---- Boy / kilo (zabıta, itfaiye vb.) --------------------------------
    if any(re.search(r"\bboy\w*", n) and re.search(r"1[.,]\d{2}\s*(?:m|metre)|\d{3}\s*cm|kilo", n) for _, n in mandatory):
        add("Boy / kilo", "unknown", "İlanda boy-kilo şartı var; resmî ilandan kendi ölçülerinizle doğrulayın.")

    # ---- Vardiya ---------------------------------------------------------
    if any("vardiya" in n for _, n in mandatory):
        shifts = candidate.get("accepts_shifts")
        if shifts is True:
            add("Vardiya", "met", "Vardiyalı çalışma şartını kabul ediyorsunuz.")
        elif shifts is False:
            add("Vardiya", "not_met", "İlan vardiyalı çalışma içeriyor; profilinizde vardiya kabul edilmiyor.")
        else:
            add("Vardiya", "unknown", "Vardiyalı çalışma şartı var; profilde tercih belirtilmemiş.")


def _blank_to_none(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def parse_kpss_scores(stored_profile) -> dict[str, float]:
    """Profildeki bütün KPSS puanlarını {"P3": 87.6} biçiminde döndürür."""
    get = (
        stored_profile.get
        if isinstance(stored_profile, dict)
        else lambda key, default=None: getattr(stored_profile, key, default)
    )
    scores: dict[str, float] = {}
    raw = get("kpss_scores")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                scores[str(key).strip().upper()] = float(value)
            except (TypeError, ValueError):
                continue
    legacy = get("kpss_p3")
    if legacy is not None and not scores:
        legacy_type = str(get("kpss_score_type") or "P3").strip().upper() or "P3"
        scores[legacy_type] = float(legacy)
    return scores


def build_candidate_profile(stored_profile=None):
    stored_profile = stored_profile or {}
    get = (
        stored_profile.get
        if isinstance(stored_profile, dict)
        else lambda key, default=None: getattr(stored_profile, key, default)
    )
    scores = parse_kpss_scores(stored_profile)
    best_type = max(scores, key=scores.get) if scores else ""
    primary = "P3" if "P3" in scores else best_type
    return {
        "degree": get("degree") or "",
        "department": get("department") or "",
        "department_aliases": get("department_aliases") or "",
        "faculty": get("faculty") or "",
        "university": get("university") or "",
        "kpss_score_type": primary,
        "kpss_score": scores.get(primary),
        "kpss_scores": scores,
        "preferred_locations": get("preferred_locations") or "Türkiye geneli",
        "accepts_shifts": get("accepts_shifts"),
        "yds_score": _blank_to_none(get("yds_score")),
        "age": _blank_to_none(get("age")),
        "driver_license": _blank_to_none(get("driver_license")),
        "gender": get("gender") or "",
        "special_status": get("special_status") or "",
        "experience_years": _blank_to_none(get("experience_years")),
        "has_internship": _blank_to_none(get("has_internship")),
        "internship_description": get("internship_description") or "",
        "certificates": _blank_to_none(get("certificates")),
        "programming_language_evidence": _blank_to_none(get("programming_language_evidence")),
        "skills": get("skills") or "",
    }
