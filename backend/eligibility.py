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
from functools import lru_cache
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


_TURKISH_FOLD = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})


def normalize_text(value):
    return _normalize_cached(value) if isinstance(value, str) and value else ""


@lru_cache(maxsize=4096)
def _normalize_cached(value: str) -> str:
    # Aynı ilan metni her kadro ve her şart için yeniden sadeleştirilir; sonuç önbelleğe alınır.
    value = unicodedata.normalize("NFKD", value.translate(_TURKISH_FOLD).casefold())
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
    if "yuksek lisans" in text or "lisansustu" in text or "master" in text:
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
    if re.search(r"doktora|doktora dereces", text):
        levels.add(5)
    if re.search(r"yuksek lisans|lisansustu|lisans ustu", text):
        levels.add(4)
    if re.search(r"(?<!on )(?<!on)(?<!yuksek )lisans(?! ?ustu)", text) or re.search(r"dort yillik|4 yillik|fakulte", text):
        levels.add(3)
    if re.search(r"ortaogretim|lise(?:\s|$|,)|lise ve dengi|lise veya dengi", text):
        levels.add(1)
    if re.search(r"yuksekogrenim|yuksekogretim kurum|yuksek ogrenim", text) and not levels:
        levels.add(2)  # herhangi bir yükseköğrenim: en az ön lisans
    return levels


def _assess_education(candidate, evidence, codes, title="", position="", position_specific=False):
    """(status, açıklama) döndürür. status: met | not_met | unknown."""
    level = degree_level(candidate.get("degree", ""))
    names = _department_names(candidate)
    department_label = candidate.get("department") or "bölümünüz"
    text = re.sub(r"\s+", " ", normalize_text(" ".join(evidence)))

    # Açıkça istenen lisansüstü düzey, genel 4001 gibi lisans kodlarının
    # önüne geçer; lisans mezununu yüksek lisans şartlı ilana uygun sayma.
    levels = _required_levels(text)
    if levels and level is not None and level < min(levels):
        return "not_met", (
            f"İlan en az {LEVEL_NAMES[min(levels)]} mezuniyeti istiyor; "
            f"profilinizdeki öğrenim düzeyi {LEVEL_NAMES.get(level, 'daha düşük')}."
        )

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

    # 2. Adayın bölümü ilanda açıkça geçiyor mu?
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
        if not position_specific and level is not None and re.search(
            r"(?<!fakultelerin )(?<!fakultelerinin )(?<!belirtilen )herhangi bir "
            + ("lisans" if level >= 3 else "on ?lisans" if level == 2 else "ortaogretim")
            + r" (?:program|bolum)",
            text,
        ) and not re.search(r"(?:fakultelerin|fakultelerinin|belirtilen fakulte)[^.]{0,60}herhangi bir", text):
            return "unknown", (
                "İlanda belirli bölümler isteyen kadroların yanında herhangi bir programdan mezunları kabul eden "
                "kadro da görünüyor; hangi pozisyon olduğu resmî ilandan doğrulanmalı."
            )
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

    def add(name, status, detail, evidence=""):
        requirements.append({
            "name": name, "status": status, "detail": detail,
            "evidence": " ".join(str(evidence or "").split())[:420],
        })
        {"met": reasons, "not_met": mismatches, "unknown": unknowns}[status].append(detail)

    education_quote = " ".join(education_evidence)[:420]
    reference_date = _job_value(job, "reference_date", None) or date.today()

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
        # Akademik kadrolar KPSS ile değil ALES/yabancı dil ile alınır; yine de adayın bölümü
        # aranıyorsa ilan elenmez, doğrulanacak şartlarıyla gösterilir.
        rank_text = normalize_text(f"{position} {title}")
        level = degree_level(candidate.get("degree", ""))
        needs_doctorate = any(word in rank_text for word in ("ogretim uyesi", "ogr. uyesi", "profesor", "prof. dr", "docent", "doc. dr", "dr. ogr", "dr.ogr"))
        if needs_doctorate and level is not None and level < 5:
            education_status, education_detail = "not_met", "Öğretim üyesi kadrosu doktora gerektirir; profilinizdeki öğrenim düzeyi yeterli değil."
        else:
            education_status, education_detail = _assess_education(candidate, education_evidence, codes, title, position, position_specific)
        add("Eğitim", education_status, education_detail, education_quote)
        if education_status != "not_met":
            add("Akademik şartlar", "unknown", (
                "Akademik kadro: KPSS aranmaz; ALES, yabancı dil ve (araştırma görevlisi için) lisansüstü öğrencilik "
                "şartları resmî ilandan doğrulanmalı."
            ))
    else:
        education_status, education_detail = _assess_education(candidate, education_evidence, codes, title, position, position_specific)
        if not has_detail and education_status == "unknown":
            education_detail = "İlanın ayrıntılı şartları henüz okunamadı; yalnızca liste bilgisi var."
        add("Eğitim", education_status, education_detail, education_quote)

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
    kpss_quote = next(
        (sentence for sentence, normalized in sentences
         if "kpss" in normalized and (_KPSS_TYPE.search(normalized) or re.search(r"\d{2}", normalized))),
        "",
    ) or " ".join(filter(None, (
        str(_job_value(job, "kpss_score_type", "") or ""),
        f"taban {minimum:g}" if minimum is not None else "",
    )))
    if not academic and (kpss_types or minimum is not None):
        usable = [kind for kind in kpss_types if kind in scores]
        if not scores:
            add("KPSS", "unknown", "Profilde KPSS puanı girilmemiş.", kpss_quote)
        elif kpss_types and not usable:
            kpss_status = "not_met"
            add("KPSS", "not_met", (
                f"İlan {'/'.join(kpss_types)} puan türünü istiyor; profilinizde bu türde puan yok "
                f"(kayıtlı: {', '.join(sorted(scores))})."
            ), kpss_quote)
        elif not kpss_types:
            add("KPSS", "unknown", (
                f"İlan en az {minimum:g} KPSS puanı istiyor ancak puan türü metinden okunamadı; resmî ilandan doğrulanmalı."
            ), kpss_quote)
        else:
            used = max(usable, key=lambda kind: scores[kind])
            score = scores[used]
            # Kanıt olarak, kullanılan puan türünün geçtiği cümle gösterilir.
            kpss_quote = next(
                (sentence for sentence, normalized in sentences
                 if "kpss" in normalized and f"P{int(used[1:])}" in {f"P{int(n)}" for n in _KPSS_TYPE.findall(normalized)}),
                kpss_quote,
            )
            candidate_kpss_type, candidate_kpss_score = used, score
            if minimum is not None and score < minimum:
                kpss_status = "not_met"
                add("KPSS", "not_met", f"{used} puanınız {score:.2f}; ilanın taban puanı {minimum:g}.", kpss_quote)
            elif minimum is not None:
                kpss_status = "met"
                add("KPSS", "met", f"{used} puanınız {score:.2f}; taban puan {minimum:g} şartını karşılıyor.", kpss_quote)
            else:
                kpss_status = "met"
                add("KPSS", "met", f"{used} puanınız {score:.2f}; puan türü eşleşiyor. Taban puan yok, başvuru şartı karşılanıyor.", kpss_quote)
    elif not academic and mentions_kpss:
        add("KPSS", "unknown", "İlanda KPSS şartı var ancak puan türü/taban puan metinden okunamadı; resmî ilandan doğrulanmalı.", kpss_quote)

    if not academic:
        _assess_other_requirements(candidate, description, mandatory, normalized_text, add, reference_date)

    # OCR ile okunan metin harf/sayı hatası içerebilir: otomatik karar verilmez.
    if _job_value(job, "ocr", False):
        add("Belge okuma", "unknown", (
            "İlan taranmış PDF'ten OCR ile okundu; harf ve sayılar hatalı olabilir. "
            "Şartları resmî PDF'ten kontrol edip elle doğrulayın."
        ))

    # İlan metni okunduysa, aranmayan yaygın şartlar "aranmıyor" olarak ayrıca gösterilir
    # (okunamayan bilgiyle karıştırılmaması için).
    if has_detail and not academic:
        named = {item["name"] for item in requirements}
        for name, label in NOT_REQUIRED_LABELS:
            if name not in named:
                requirements.append({"name": name, "status": "not_required", "detail": f"İlan metninde {label} aranmıyor.", "evidence": ""})

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


NOT_REQUIRED_LABELS = (
    ("KPSS", "KPSS puan şartı"), ("Yaş", "yaş sınırı"), ("YDS", "yabancı dil puanı"), ("Deneyim", "mesleki deneyim"),
    ("Sürücü belgesi", "sürücü belgesi"), ("Sertifika", "sertifika"),
)


def candidate_age_on(candidate, reference_date):
    """Yaş, bugüne göre değil ilanın başvuru tarihine göre hesaplanır."""
    birth = candidate.get("birth_date")
    if isinstance(birth, str) and birth:
        try:
            birth = date.fromisoformat(birth[:10])
        except ValueError:
            birth = None
    if isinstance(birth, date):
        years = reference_date.year - birth.year - ((reference_date.month, reference_date.day) < (birth.month, birth.day))
        return years
    return candidate.get("age")


def candidate_experience_on(candidate, reference_date):
    """Deneyim kayıtlarından başvuru tarihine kadar geçen toplam süre (yıl)."""
    records = candidate.get("experiences") or []
    total_months = 0
    counted = False
    for record in records:
        start = _parse_month(record.get("start"))
        end = _parse_month(record.get("end")) or reference_date
        if start is None:
            continue
        end = min(end, reference_date)
        if end > start:
            total_months += (end.year - start.year) * 12 + (end.month - start.month)
            counted = True
    if counted:
        return round(total_months / 12, 1)
    return candidate.get("experience_years")


def _parse_month(value):
    if not value:
        return None
    try:
        text = str(value)
        return date.fromisoformat(text if len(text) > 7 else f"{text}-01")
    except ValueError:
        return None


def _assess_other_requirements(candidate, description, mandatory, normalized_text, add, reference_date=None):
    reference_date = reference_date or date.today()

    def first(predicate):
        return next((sentence for sentence, normalized in mandatory if predicate(normalized)), "")

    # ---- YDS / yabancı dil -----------------------------------------------
    yds_minimum, yds_required, yds_quote = None, False, ""
    for sentence, normalized in mandatory:
        if not re.search(r"\b(?:yds|e-yds|yokdil|yabanci dil|ingilizce|almanca|fransizca|arapca|rusca)\b", normalized):
            continue
        minimum_match = re.search(r"(?:en az|asgari)\s*(\d{2,3}(?:[.,]\d+)?)", normalized)
        if minimum_match and re.search(r"puan|duzey|seviye", normalized):
            yds_minimum = min(yds_minimum or 999.0, float(minimum_match.group(1).replace(",", ".")))
            yds_required, yds_quote = True, yds_quote or sentence
        elif any(term in normalized for term in ("puan almak", "puan almis olmak", "belgeye sahip olmak")):
            yds_required, yds_quote = True, yds_quote or sentence
            if "c duzeyinde" in normalized or "c seviye" in normalized:
                yds_minimum = 70.0
    if yds_required and (yds_minimum is not None or not _has_zero_score_fallback(description)):
        yds = candidate.get("yds_score")
        if yds is None:
            detail = (
                f"İlan en az {yds_minimum:g} YDS/yabancı dil puanı istiyor; profilde dil puanı belirtilmemiş."
                if yds_minimum else "YDS/yabancı dil şartı var; profilde dil puanı belirtilmemiş."
            )
            add("YDS", "unknown", detail, yds_quote)
        elif yds_minimum is not None and float(yds) < yds_minimum:
            add("YDS", "not_met", f"YDS puanınız {float(yds):g}; ilan en az {yds_minimum:g} istiyor.", yds_quote)
        else:
            add("YDS", "met", f"YDS puanınız ({float(yds):g}) ilanın şartını karşılıyor.", yds_quote)

    # ---- Yaş (başvuru tarihine göre) -------------------------------------
    age_limit, age_required, age_quote = None, False, ""
    for sentence, normalized in mandatory:
        match = re.search(
            r"(\d{2})\s*(?:\([^)]{0,20}\)\s*)?yas\w*\s+(?:gununu\s+)?(?:doldurmamis|bitirmemis|gun almamis|asmamis|gecmemis)",
            normalized,
        )
        if match:
            age_limit, age_required, age_quote = int(match.group(1)), True, sentence
        elif "yas siniri" in normalized or "ust yas" in normalized:
            age_required, age_quote = True, age_quote or sentence
    if age_required:
        age = candidate_age_on(candidate, reference_date)
        when = f"{reference_date:%d.%m.%Y} itibarıyla"
        if age is None:
            add("Yaş", "unknown", f"İlanda {f'{age_limit} ' if age_limit else ''}yaş sınırı var; profilde doğum tarihi belirtilmemiş.", age_quote)
        elif age_limit is not None and int(age) >= age_limit:
            add("Yaş", "not_met", f"{when} {int(age)} yaşındasınız; ilan {age_limit} yaşını doldurmamış olmayı istiyor.", age_quote)
        elif age_limit is None:
            add("Yaş", "unknown", "İlanda yaş sınırı var ancak sınır metinden okunamadı; resmî ilandan doğrulayın.", age_quote)
        else:
            add("Yaş", "met", f"{when} {int(age)} yaşındasınız; yaş şartı karşılanıyor (ilandaki esas tarihi ayrıca kontrol edin).", age_quote)

    # ---- Deneyim (başvuru tarihine göre) ---------------------------------
    experience_years, experience_required, experience_quote = None, False, ""
    for sentence, normalized in mandatory:
        if not any(term in normalized for term in ("deneyim", "tecrube", "calismis olmak")):
            continue
        years = re.search(r"en az\s+(\d+)\s*(?:\([^)]*\)\s*)?yil", normalized)
        if years:
            experience_years, experience_required = min(experience_years or 99, int(years.group(1))), True
            experience_quote = experience_quote or sentence
        elif re.search(r"sahip olmak|aranir|zorunlu|bulunmak", normalized):
            experience_required, experience_quote = True, experience_quote or sentence
    if experience_required:
        have = candidate_experience_on(candidate, reference_date)
        wanted = f"en az {experience_years} yıl " if experience_years else ""
        if candidate.get("experience_state") == "none":
            add("Deneyim", "not_met", f"İlan {wanted}mesleki deneyim istiyor; profilinizde “mesleki deneyimim yok” işaretli.", experience_quote)
        elif have is None:
            add("Deneyim", "unknown", f"İlan {wanted}mesleki deneyim istiyor; profilde deneyim bilgisi belirtilmemiş.", experience_quote)
        elif experience_years is not None and float(have) < experience_years:
            add("Deneyim", "not_met", f"Başvuru tarihinde deneyiminiz {float(have):g} yıl; ilan en az {experience_years} yıl istiyor.", experience_quote)
        else:
            add("Deneyim", "met", f"{float(have):g} yıllık deneyiminiz ilanın şartını karşılıyor.", experience_quote)

    # ---- Sürücü belgesi --------------------------------------------------
    license_quote = first(lambda n: re.search(r"surucu belgesi|ehliyet", n) and re.search(r"zorunlu|sahip olmak|aranir|gereklidir", n))
    if license_quote:
        have = candidate.get("driver_license")
        if have is None:
            add("Sürücü belgesi", "unknown", "Sürücü belgesi şartı var; profilde ehliyet bilgisi belirtilmemiş.", license_quote)
        elif have:
            add("Sürücü belgesi", "met", "Sürücü belgesi şartı karşılanıyor (sınıfını ilandan kontrol edin).", license_quote)
        else:
            add("Sürücü belgesi", "not_met", "İlan sürücü belgesi istiyor; profilinizde sürücü belgesi yok.", license_quote)

    # ---- Sertifika -------------------------------------------------------
    cert_pairs = [
        (sentence, n) for sentence, n in mandatory
        if "sertifika" in n and re.search(r"zorunlu|sahip olmak|belgelemek|ibraz|en az birine", n)
    ]
    # "Bilgisayar sertifikası VEYA okulda bilgisayar dersi görmüş olmak": iki seçenekten biri yeterlidir.
    computer_option = next(
        (pair for pair in cert_pairs if "bilgisayar" in pair[1] and "veya" in pair[1] and "bilgisayar dersi" in pair[1]), None,
    )
    if computer_option:
        cert_pairs = [pair for pair in cert_pairs if not ("bilgisayar" in pair[1] and "sertifika" in pair[1])]
        department = normalize_text(f"{candidate.get('department', '')} {candidate.get('department_aliases', '')}")
        owned_text = normalize_text(str(candidate.get("certificates") or ""))
        if any(word in department for word in ("bilgisayar", "yazilim", "bilisim")):
            add("Bilgisayar belgesi", "met", "Sertifika ya da okulda bilgisayar dersi isteniyor; bölümünüz bilgisayar dersi içerir (transkriptle belgelenir).", computer_option[0])
        elif "bilgisayar" in owned_text:
            add("Bilgisayar belgesi", "met", "Profilinizde bilgisayar sertifikası var.", computer_option[0])
        else:
            add("Bilgisayar belgesi", "unknown", "Bilgisayar sertifikası ya da okulda bilgisayar dersi görmüş olmak isteniyor; transkriptinizden doğrulayın.", computer_option[0])
    if cert_pairs:
        quote = cert_pairs[0][0]
        owned = [normalize_text(c).strip() for c in re.split(r"[,;\n]", str(candidate.get("certificates") or "")) if c.strip()]
        if not owned:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı var; profilde sertifika belirtilmemiş.", quote)
        elif any(cert in n for cert in owned for _, n in cert_pairs):
            add("Sertifika", "met", "Profildeki sertifika ilanın istediğiyle eşleşiyor.", quote)
        else:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı var; profildeki sertifikalarla eşleşme resmî ilandan doğrulanmalı.", quote)

    # ---- Programlama dili belgeleme --------------------------------------
    if re.search(r"programlama dillerinden en az (?:iki|ikisini|2)", normalized_text):
        quote = first(lambda n: "programlama dil" in n)
        if not candidate.get("programming_language_evidence"):
            add("Programlama dilleri", "unknown", "En az iki programlama dilini bildiğini belgeleme şartı var; profilde belirtilmemiş.", quote)
        else:
            add("Programlama dilleri", "met", "Profilde programlama dili bilgisi bulunuyor.", quote)

    # ---- Cinsiyet (kadro satırında belirtilmişse) --------------------------
    gender_match = re.search(r"cinsiyet\w*\s*[:：]?\s*(erkek|kadin)(?!\s*/|\s*(?:ve|veya)\s)", normalized_text)
    if gender_match:
        wanted = gender_match.group(1)
        have = normalize_text(str(candidate.get("gender") or "")).strip()
        label = "Erkek" if wanted == "erkek" else "Kadın"
        if not have:
            add("Cinsiyet", "unknown", f"Kadro {label} adaylar için; profilde cinsiyet belirtilmemiş.", f"Cinsiyet: {label}")
        elif have == wanted:
            add("Cinsiyet", "met", f"Kadro {label} adaylar için; profilinizle uyumlu.", f"Cinsiyet: {label}")
        else:
            add("Cinsiyet", "not_met", f"Kadro yalnızca {label} adaylar için.", f"Cinsiyet: {label}")

    # ---- Boy / kilo (zabıta, itfaiye vb.) --------------------------------
    body_quote = first(lambda n: re.search(r"\bboy\w*", n) and re.search(r"1[.,]\d{2}\s*(?:m|metre)|\d{3}\s*cm|kilo", n))
    if body_quote:
        add("Boy / kilo", "unknown", "İlanda boy-kilo şartı var; resmî ilandan kendi ölçülerinizle doğrulayın.", body_quote)

    # ---- Vardiya ---------------------------------------------------------
    shift_quote = first(lambda n: "vardiya" in n)
    if shift_quote:
        shifts = candidate.get("accepts_shifts")
        if shifts is True:
            add("Vardiya", "met", "Vardiyalı çalışma şartını kabul ediyorsunuz.", shift_quote)
        elif shifts is False:
            add("Vardiya", "not_met", "İlan vardiyalı çalışma içeriyor; profilinizde vardiya kabul edilmiyor.", shift_quote)
        else:
            add("Vardiya", "unknown", "Vardiyalı çalışma şartı var; profilde tercih belirtilmemiş.", shift_quote)


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


def _json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


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

    # Eğitim kayıtları varsa en yüksek düzey ve bütün bölümler kullanılır.
    educations = [item for item in _json_list(get("educations")) if isinstance(item, dict)]
    degree = get("degree") or ""
    department = get("department") or ""
    aliases = [get("department_aliases") or ""]
    if educations:
        ranked = sorted(educations, key=lambda item: degree_level(str(item.get("level") or "")) or 0, reverse=True)
        degree = str(ranked[0].get("level") or degree)
        top_level = degree_level(degree) or 0
        departments = [str(item.get("department") or "").strip() for item in ranked if str(item.get("department") or "").strip()]
        # Bölüm eşleşmesinde yalnızca en yüksek düzeydeki (ve lisans üstü) kayıtlar esas alınır.
        primary_departments = [
            str(item.get("department") or "").strip() for item in ranked
            if (degree_level(str(item.get("level") or "")) or 0) >= min(top_level, 3) and str(item.get("department") or "").strip()
        ] or departments
        if primary_departments:
            department = primary_departments[0]
            aliases.extend(primary_departments[1:])

    birth = get("birth_date")
    experiences = [item for item in _json_list(get("experiences")) if isinstance(item, dict)]
    preferences = get("preferences")
    if isinstance(preferences, str):
        try:
            preferences = json.loads(preferences or "{}")
        except ValueError:
            preferences = {}
    return {
        "degree": degree,
        "department": department,
        "department_aliases": ", ".join(item for item in aliases if item),
        "faculty": get("faculty") or "",
        "university": get("university") or "",
        "kpss_score_type": primary,
        "kpss_score": scores.get(primary),
        "kpss_scores": scores,
        "preferred_locations": get("preferred_locations") or "Türkiye geneli",
        "preferences": preferences if isinstance(preferences, dict) else {},
        "accepts_shifts": get("accepts_shifts"),
        "yds_score": _blank_to_none(get("yds_score")),
        "age": _blank_to_none(get("age")),
        "birth_date": birth.isoformat() if isinstance(birth, date) else (birth or None),
        "driver_license": _blank_to_none(get("driver_license")),
        "gender": get("gender") or "",
        "special_status": get("special_status") or "",
        "military_status": get("military_status") or "",
        "experience_years": _blank_to_none(get("experience_years")),
        "experiences": experiences,
        "experience_state": get("experience_state") or "",
        "has_internship": _blank_to_none(get("has_internship")),
        "internship_description": get("internship_description") or "",
        "certificates": _blank_to_none(get("certificates")),
        "programming_language_evidence": _blank_to_none(get("programming_language_evidence")),
        "skills": get("skills") or "",
    }
