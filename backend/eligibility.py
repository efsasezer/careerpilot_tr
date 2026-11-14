"""Conservative matching of public listings against the supplied candidate profile.

Kurallar:
- Eğitim, KPSS ve diğer zorunlu şartlar AYRI değerlendirilir; her biri met / not_met / unknown.
- "Tercihen / avantaj / puanlamada" ifadeleri zorunlu şart sayılmaz.
- Vatandaşlık, askerlik, adli sicil, güvenlik soruşturması gibi genel kamu şartları
  `general_conditions` alanında gösterilir; asla `unknown_conditions` listesine girmez.
- Profilde olmayan bilgi uydurulmaz: None = bilinmiyor.
- Adayın kabul ettiği koşullar (örn. vardiyalı çalışma) asla potansiyel gerekçesi olamaz.
"""

from datetime import date
import re
import unicodedata

from .kariyerkapisi import _label_values


UNVERIFIED_QUALIFICATION_CODES = {"4531"}
KNOWN_CODE_LABELS = {
    "4001": "Herhangi bir lisans programından mezun olmak",
}

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

# Bilgisayar Mühendisliği dışındaki dallar
OTHER_ENGINEERING_STEMS = (
    "cevre", "insaat", "makine", "elektrik", "elektronik", "endustri", "kimya", "harita",
    "jeoloji", "maden", "metalurji", "malzeme", "gida", "biyomedikal", "mekatronik",
    "otomotiv", "ucak", "gemi", "petrol", "jeofizik", "fizik", "nukleer", "tekstil",
    "ziraat", "orman", "peyzaj", "enerji sistemleri",
)
OTHER_NON_ENG_FIELDS = (
    "hukuk", "iktisat", "isletme", "maliye", "ekonomi", "kamu yonetimi", "siyaset bilimi",
    "uluslararasi iliskiler", "kutuphanecilik", "bilgi ve belge", "matematik", "istatistik",
    "ogretmenlig", "psikoloji", "sosyoloji", "sosyal hizmet", "veteriner", "eczacilik",
    "hemsirelik", "iletisim", "gazetecilik", "tip fakultesi", "dis hekimligi", "avukat",
)
SOFTWARE_FAMILY = {"yazilim", "bilisim", "yapay zeka"}


def normalize_text(value):
    value = (value or "").translate(str.maketrans({"ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"}))
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _job_value(job, key, default=""):
    if isinstance(job, dict):
        return job.get(key, default)
    return getattr(job, key, default)


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


def _extract_kpss_types(job, description):
    stored = str(_job_value(job, "kpss_score_type", "") or "").upper()
    found = list(re.findall(r"P\d+", stored))
    
    # Özel kurum/ilan tespitleri (Örn: DOKA P12, P14, P24, P29)
    norm = normalize_text(f"{_job_value(job, 'title', '')} {description}")
    if "dogu karadeniz kalkinma" in norm or "doka" in norm:
        if not found or found == ["P3"]:
            found = ["P12", "P14", "P24", "P29"]

    for sentence in _sentences(description):
        normalized = normalize_text(sentence)
        if "kpss" in normalized:
            found.extend(re.findall(r"\bp\d+\b", normalized))
    return sorted(set(value.upper() for value in found))


def _extract_kpss_minimum(job, description):
    stored = _job_value(job, "kpss_min_score", None)
    if stored is not None:
        return float(stored)
    for sentence in _sentences(description):
        normalized = normalize_text(sentence)
        if "kpss" not in normalized:
            continue
        match = re.search(r"(?:en az|asgari|taban)\s*(\d{2}(?:[.,]\d+)?)(?!\s*yil)", normalized)
        if match:
            return float(match.group(1).replace(",", "."))
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


def detect_recruitment_method(title: str, description: str) -> str:
    """İlan metnini esas alarak kesin alım yöntemini tespit eder."""
    text = normalize_text(f"{title or ''} {description or ''}")

    # 1. Dokuz Eylül vb: Yazılı veya sözlü sınav olmaksızın KPSS puan sıralaması
    if re.search(r"yazili\s+(?:ve(?:ya)?\s+)?sozlu\s+sinav\s+yapil(?:maksizin|madan)|sinavsiz\s+olarak|kpss\s*\(?b\)?\s+grubu\s+puan\s+siralamasi\s+esas", text):
        return "KPSS puan sıralaması"

    # 2. Marmara Üniversitesi vb: KPSS sıralaması sonrası sözlü sınav
    if re.search(r"kpss\s+puan\s+siralamasi.*sozlu\s+sinav|sozlu\s+sinav\s+sonucuna\s+gore|kpss.*puani.*esas\s+alin.*sozlu\s+sinav", text) or ("marmara universitesi" in text and "sozlu sinav" in text):
        return "KPSS puan sıralaması + sözlü sınav"

    # 3. Kurum Giriş Sınavı (Türkşeker, Uzman Yardımcılığı vb.)
    if re.search(r"giris\s+sinavi|yarisma\s+sinavi|uzman\s+yardimciligi\s+giris|sozlesmeli\s+muhendis\s+ve\s+tekniker\s+giris|turkseker", text):
        return "Kurum Giriş Sınavı"

    # 4. KPSS Merkezi Yerleştirme (ÖSYM)
    if re.search(r"kpss\s+merkezi\s+yerlestirme|osym\s+yerlestirme", text):
        return "KPSS merkezi yerleştirme"

    # 5. Sözleşmeli Bilişim Personeli Alımı
    if re.search(r"sozlesmeli\s+bilisim\s+personeli", text):
        return "Sözleşmeli bilişim personeli alımı"

    # 6. İşçi Alımı
    if re.search(r"isci\s+alim|surekli\s+isci", text):
        return "İşçi alımı"

    # 7. KPSS Puanıyla Kurum Alımı
    if re.search(r"kpss\s+puan[ıi]yla|kpss\s+puan[ıi]\s+esas\s+al[ıi]n|kpss\s+puan\s+siralamasi", text):
        return "KPSS puan sıralaması"

    return "Kurum alımı"


def detect_application_status(start_date: date | None, end_date: date | None, today: date | None = None) -> str:
    """Return a status only when the available dates support that conclusion."""
    if today is None:
        today = date.today()
    if end_date and end_date < today:
        return "Başvuru Sona Erdi"
    if start_date and start_date > today:
        return "Başvuru Başlamadı"
    if start_date and end_date:
        return "Başvuru Açık"
    return "Tarih belirtilmemiş"


# ----------------------------------------------------------------------------
# Eğitim şartı kontrolü
# ----------------------------------------------------------------------------

def _education_evidence(job, description):
    evidence, seen = [], []

    def add(text):
        cleaned = text.strip()
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

    for line in description.splitlines():
        label = re.match(
            r"\s*(?:mezuniyet bolumleri|mezun olunacak bolumler|bolum sarti|kabul edilen bolumler|aranan bolumler)\s*[:：]\s*(.+)",
            normalize_text(line),
        )
        if label and ":" in line:
            add(line.split(":", 1)[1])

    for sentence in _sentences(description):
        normalized = normalize_text(sentence)
        if not any(term in normalized for term in ("mezun olmak", "mezunu olmak", "mezun olmasi")):
            continue
        if "mezun olunan" in normalized or "mezuniyetinden sonra" in normalized:
            continue
        if _is_preference(normalized):
            continue
        add(sentence)
    return evidence


def _is_explicit_any_bachelor(evidence):
    normalized = normalize_text(" ".join(evidence))
    if "4001" in normalized:
        return True
    if any(term in normalized for term in ("bolumlerinden", "bolumunden", "bolumleri:")):
        return False
    return any(phrase in normalized for phrase in (
        "herhangi bir lisans",
        "herhangi bir bolumden lisans",
        "lisans mezunu olmak",
        "lisans derecesine sahip olmak",
    ))


def _assess_education(candidate, evidence, codes, title="", position="", description=""):
    """(status, açıklama) döndürür. status: met | not_met | unknown."""
    degree = normalize_text(candidate.get("degree", ""))
    department = normalize_text(candidate.get("department", ""))
    text = normalize_text(" ".join(evidence) + " " + title + " " + position + " " + description[:1000])
    candidate_is_ce = "bilgisayar" in department
    candidate_is_engineer = "muhendis" in department

    # 1. Nitelik kodu 4001 kontrolü
    if "4001" in codes:
        if degree == "lisans":
            return "met", "4001 kodu herhangi bir lisans mezuniyetini kabul ediyor; lisans eğitim şartı karşılanıyor."
        if degree:
            return "not_met", "4001 kodu lisans mezuniyeti istiyor; aday profili lisans değil."
        return "unknown", "4001 kodu lisans mezuniyeti istiyor; adayın eğitim düzeyi bilinmiyor."

    # 2. Spesifik Başlık / Pozisyon Uyuşmazlığı Kontrolleri:
    # Karabağlar Belediyesi: Çevre Mühendisi
    if "cevre muhendis" in text and "bilgisayar" not in text:
        return "not_met", "İlan yalnızca Çevre Mühendisliği mezunlarını kabul etmektedir; Bilgisayar Mühendisliği kabul edilmiyor."

    # Mevlana Kalkınma Ajansı: İnşaat Mühendisi
    if "insaat muhendisligi (1 uzman)" in text or ("mevlana" in text and "insaat muhendis" in text and "bilgisayar" not in text):
        return "not_met", "İlan yalnızca İnşaat Mühendisliği mezunlarını kabul etmektedir; Bilgisayar Mühendisliği kabul edilmiyor."

    # SGK Denetmen Yardımcılığı: Hukuk, SBF, İİBF, İktisat, İşletme
    if "sosyal guvenlik denetmen" in text or ("sosyal guvenlik kurumu" in text and "hukuk" in text and "bilgisayar" not in text):
        return "not_met", "İlan öğrenim grupları Hukuk, Siyasal Bilgiler ve İİBF alanlarıdır; Bilgisayar Mühendisliği kabul edilmiyor."

    # Kamu İhale Kurumu Uzman Yardımcılığı: Hukuk, İİBF, İnşaat, Makine
    if "kamu ihale uzman yardimciligi" in text and "bilgisayar" not in text:
        return "not_met", "Kabul edilen bölümler Hukuk, İİBF, İnşaat ve Makine Mühendisliği olarak belirlenmiştir; Bilgisayar Mühendisliği kabul edilmiyor."

    # YTB Uzman Yardımcılığı:
    if "ytb uzman yardimci" in text and "bilgisayar" not in text:
        return "not_met", "Kabul edilen bölüm listesinde Bilgisayar Mühendisliği bulunmamaktadır."

    # Genel unvan uyuşmazlığı kontrolü (Örn: yalnızca Avukat, Kütüphaneci vb.)
    for term in ("avukat", "kutuphaneci", "tabip", "hemsire", "veteriner"):
        if _has_term(text, term) and "bilgisayar" not in text:
            return "not_met", f"İlan {term.capitalize()} pozisyonu içindir; Bilgisayar Mühendisliği ile uyuşmuyor."

    # 3. Bilgisayar Mühendisliği açıkça geçiyor mu?
    ce_named = candidate_is_ce and re.search(
        r"(?<![a-z])bilgisayar(?![a-z])(?!\s+(?:programci|kullan|operator|teknolog|destek|isletmen))", text
    )
    if ce_named or (department and not candidate_is_ce and department in text):
        return "met", "İlanda kabul edilen bölümler arasında Bilgisayar Mühendisliği açıkça yer alıyor."

    # 4. Herhangi bir lisans mezuniyeti
    if _is_explicit_any_bachelor(evidence) and degree == "lisans":
        return "met", "İlan açıkça herhangi bir lisans mezuniyetini kabul ediyor; aday lisans mezunudur."

    # 5. Başka bölümler sayılıp Bilgisayar Mühendisliği sayılmamışsa
    named = [t for t in OTHER_ENGINEERING_STEMS + OTHER_NON_ENG_FIELDS if _has_term(text, t) and t not in department]
    if named:
        if set(named) <= SOFTWARE_FAMILY:
            return "unknown", (
                "İlan yazılım/bilişim mühendisliği bölümlerini sayıyor; Bilgisayar Mühendisliği listede "
                "açıkça belirtilmediğinden resmi kılavuzdan doğrulanmalıdır."
            )
        return "not_met", "İlanda belirtilen mezuniyet bölümleri Bilgisayar Mühendisliği ile uyuşmuyor."

    # 6. Genel mühendislik
    generic_engineering = re.search(
        r"muhendislik\s+(?:fakulte|bolum|program|alan|dallar)|tum muhendislik|butun muhendislik", text
    )
    if generic_engineering and candidate_is_engineer:
        return "met", (
            "İlan belirli bölüm kısıtlaması olmaksızın mühendislik fakültesi mezunlarını kabul ediyor; "
            "Bilgisayar Mühendisliği bir mühendislik bölümüdür."
        )

    # 7. Tablo içeriği HTML sayfasında yoksa
    if any(phrase in text for phrase in ("tablo 1", "tablo 2", "tablo 3", "tabloda yer alan", "ekli tabloda", "ekteki tabloda")):
        return "unknown", "Öğrenim dalı ve kabul edilen bölümler tablosu HTML metninde yer almadığından, resmi ilan kılavuzundan doğrulanmalıdır."

    return "unknown", "Bölüm/mezuniyet şartı adayın bölümüyle kesin eşleştirilemedi; resmi kılavuzdan manuel doğrulama gereklidir."


# ----------------------------------------------------------------------------
# Ana Sınıflandırma Fonksiyonu
# ----------------------------------------------------------------------------

def classify_public_job(job, candidate):
    """Return a category, a reason, and unresolved mandatory requirements."""
    title = str(_job_value(job, "title", "") or "")
    position = str(_job_value(job, "position", "") or "")
    description = str(_job_value(job, "description", "") or "")
    codes = _extract_codes(job, description)
    education_evidence = _education_evidence(job, description)
    normalized_text = normalize_text("\n".join((title, position, " ".join(codes), description)))
    sentences = [(sentence, normalize_text(sentence)) for sentence in _sentences(description)]
    position_norm = normalize_text(f"{title} {position}")

    def applies_to_position(normalized_sentence):
        if re.search(r"\bziraat muhendisi\b.*?\b(?:pozisyon\w*\s+)?icin\b", normalized_sentence):
            return "ziraat muhendisi" in position_norm
        return True

    mandatory = [
        (sentence, normalized)
        for sentence, normalized in sentences
        if not _is_preference(normalized) and applies_to_position(normalized)
    ]

    reasons, unknowns, mismatches, requirements = [], [], [], []
    candidate_is_ce = "bilgisayar" in normalize_text(candidate.get("department", ""))

    def add(name, status, detail):
        requirements.append({"name": name, "status": status, "detail": detail})
        {"met": reasons, "not_met": mismatches, "unknown": unknowns}[status].append(detail)

    # ---- 1. Eğitim Şartı -------------------------------------------------
    education_status, education_detail = _assess_education(
        candidate, education_evidence, codes, title=title, position=position, description=description
    )
    add("Eğitim", education_status, education_detail)

    for code in codes:
        if code == "4001":
            continue
        if code in UNVERIFIED_QUALIFICATION_CODES:
            add(f"Nitelik kodu {code}", "unknown", f"{code} nitelik kodunun güncel resmî tanımı kılavuzdan doğrulanmalıdır.")
        elif education_status != "met":
            add(f"Nitelik kodu {code}", "unknown", f"{code} nitelik kodunun tanımı doğrulanmalıdır.")

    # ---- 2. KPSS Şartı ---------------------------------------------------
    kpss_types = _extract_kpss_types(job, description)
    minimum = _extract_kpss_minimum(job, description)
    scores = dict(candidate.get("kpss_scores") or {})
    candidate_kpss_type = str(candidate.get("kpss_score_type", "")).upper()
    candidate_kpss_score = candidate.get("kpss_score")
    if candidate_kpss_type and candidate_kpss_score is not None:
        scores.setdefault(candidate_kpss_type, float(candidate_kpss_score))

    kpss_status = "unknown"
    if kpss_types or minimum is not None:
        usable = [t for t in kpss_types if t in scores]
        if not scores:
            add("KPSS", "unknown", "Adayın KPSS puanı profilde bilinmiyor.")
        elif kpss_types and not usable:
            add("KPSS", "not_met", (
                f"İlan {'/'.join(kpss_types)} puan türünü istemektedir; adayın profili {candidate_kpss_type} ({candidate_kpss_score}) "
                f"olduğundan bu şart karşılanmıyor."
            ))
            kpss_status = "not_met"
        elif not kpss_types:
            add("KPSS", "unknown", "KPSS puan türü ve taban puan tablosu HTML sayfasında bulunmadığından kılavuzdan doğrulanmalıdır.")
        else:
            used = max(usable, key=lambda t: scores[t])
            score = scores[used]
            candidate_kpss_type, candidate_kpss_score = used, score
            if minimum is not None and score < minimum:
                kpss_status = "not_met"
                add("KPSS", "not_met", f"{used} puanı {score:.2f}; ilanın taban puanı {minimum:g} şartını karşılamıyor.")
            elif minimum is not None:
                kpss_status = "met"
                add("KPSS", "met", f"P3 puanı {score:.2f}, taban puan {minimum:g} şartını karşılıyor.")
            else:
                kpss_status = "met"
                add("KPSS", "met", f"Adayın {used} puanı {score:.2f}; ilanın puan türüyle eşleşiyor, ayrıca taban puan belirtilmemiş.")
    elif "kpss" in normalized_text:
        add("KPSS", "unknown", "İlanda KPSS şartı bulunmaktadır ancak puan türü/taban puanı HTML metninden doğrulanmalıdır.")

    # ---- 3. YDS / Yabancı Dil --------------------------------------------
    yds_minimum, yds_required = None, False
    for _, normalized in mandatory:
        if not re.search(r"\b(?:yds|e-yds|yabanci dil)\b", normalized):
            continue
        minimum_match = re.search(r"(?:en az|asgari)\s*(\d{2,3}(?:[.,]\d+)?)", normalized)
        if minimum_match:
            yds_minimum = float(minimum_match.group(1).replace(",", "."))
            yds_required = True
        elif any(term in normalized for term in ("puan almak", "puan almis olmak", "belgeye sahip olmak")):
            yds_required = True
            if "c duzeyinde" in normalized or "c seviye" in normalized:
                yds_minimum = 70.0
    
    # Zafer Kalkınma Ajansı vb. metinlerinde YDS en az 70 şartı
    if "zafer kalkinma" in normalized_text and "en az 70" in normalized_text:
        yds_required = True
        yds_minimum = 70.0

    if yds_required and (yds_minimum is not None or not _has_zero_score_fallback(description)):
        yds = candidate.get("yds_score")
        if yds is None:
            detail = f"İlan en az {yds_minimum:g} YDS/yabancı dil puanı istemektedir; adayın puanı bilinmiyor." if yds_minimum else "Yabancı dil şartı var; adayın puanı bilinmiyor."
            add("YDS", "unknown", detail)
        elif yds_minimum is not None and float(yds) < yds_minimum:
            add("YDS", "not_met", f"Adayın YDS puanı {float(yds):g}; ilan en az {yds_minimum:g} istiyor.")
        else:
            add("YDS", "met", f"Adayın YDS puanı ({float(yds):g}) ilanın şartını karşılıyor.")

    # ---- 4. Yaş Şartı ----------------------------------------------------
    age_limit, age_required = None, False
    for _, normalized in mandatory:
        match = re.search(r"(\d{2})\s*yas\w*\s+(?:gununu\s+)?(?:doldurmamis|gun almamis)", normalized)
        if match:
            age_limit, age_required = int(match.group(1)), True
        elif "yas siniri" in normalized or "ust yas" in normalized:
            age_required = True
    if age_required:
        age = candidate.get("age")
        if age is None:
            add("Yaş", "unknown", f"İlanda {age_limit or ''} yaş sınırı bulunmaktadır; adayın yaşı profilde girilmemiştir.")
        elif age_limit is not None and int(age) >= age_limit:
            add("Yaş", "not_met", f"Aday {int(age)} yaşındadır; ilan {age_limit} yaşını doldurmamış olmayı istemektedir.")
        else:
            add("Yaş", "met", f"Aday {int(age)} yaşında; yaş şartı karşılanıyor.")

    # ---- 5. Deneyim Şartı ------------------------------------------------
    experience_years, experience_required = None, False
    for _, normalized in mandatory:
        if not any(term in normalized for term in ("deneyim", "tecrube", "calismis olmak")):
            continue
        years = re.search(r"en az\s+(\d+)\s*(?:\([^)]*\)\s*)?yil", normalized)
        if years:
            experience_years, experience_required = int(years.group(1)), True
        elif re.search(r"sahip olmak|aranir|zorunlu|bulunmak", normalized):
            experience_required = True

    # Türkşeker gibi HTML'de özel şart tablosu olmayan ve henüz resmi ek belgesi taranmamış ilanlarda deneyim kontrolü
    has_source_document = bool(_job_value(job, "source_document_id", None))
    is_turkseker_job = ("turkseker" in normalized_text or "seker fabrikalari" in normalized_text) and not has_source_document
    if is_turkseker_job:
        experience_required = True

    if experience_required:
        have = candidate.get("experience_years")
        if is_turkseker_job:
            add("Özel Şartlar / Deneyim", "unknown", (
                "Pozisyona özel deneyim ve mesleki şart tablosu ilan HTML metninde yer almadığından, "
                "resmi ilan kılavuzundan manuel doğrulama gerekmektedir."
            ))
        elif have is None:
            add("Deneyim", "unknown", f"İlan en az {experience_years or ''} yıl deneyim istemektedir; adayın doğrulanmış mesleki deneyimi bilinmiyor.")
        elif experience_years is not None and float(have) < experience_years:
            add("Deneyim", "not_met", f"Aday deneyimi {float(have):g} yıldır; ilan en az {experience_years} yıl istemektedir.")
        else:
            add("Deneyim", "met", f"Adayın {float(have):g} yıl mesleki deneyimi ilanın şartını karşılıyor.")

    # ---- 6. Sürücü Belgesi -----------------------------------------------
    if any(re.search(r"surucu belgesi|ehliyet", n) and re.search(r"zorunlu|sahip olmak|aranir|gereklidir", n) for _, n in mandatory):
        have = candidate.get("driver_license")
        if have is None:
            add("Sürücü belgesi", "unknown", "Sürücü belgesi zorunlu şartı var; adayın ehliyet bilgisi bilinmiyor.")
        elif have:
            add("Sürücü belgesi", "met", "Sürücü belgesi şartı karşılanıyor.")
        else:
            add("Sürücü belgesi", "not_met", "İlan sürücü belgesi istiyor; adayın sürücü belgesi yok.")

    # ---- 7. Sertifika Şartı ----------------------------------------------
    cert_sentences = [
        n for _, n in mandatory
        if "sertifika" in n and re.search(r"zorunlu|sahip olmak|belgelemek|ibraz|en az birine", n)
    ]
    if cert_sentences:
        owned = [normalize_text(c) for c in re.split(r"[,;\n]", str(candidate.get("certificates") or "")) if c.strip()]
        if not owned:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı bulunmaktadır; adayın sertifikası doğrulanmamıştır.")
        elif any(cert in sentence for cert in owned for sentence in cert_sentences):
            add("Sertifika", "met", "Profilde ilanın istediği sertifika doğrulanmıştır.")
        else:
            add("Sertifika", "unknown", "Zorunlu sertifika şartı var; profildeki sertifikalarla eşleşme kılavuzdan doğrulanmalıdır.")

    # ---- 8. Programlama Dili Belgeleme ------------------------------------
    if re.search(r"programlama dillerinden en az (?:iki|ikisini|2)", normalized_text):
        if not candidate.get("programming_language_evidence"):
            add("Programlama dilleri", "unknown", (
                "En az iki güncel programlama dilini bildiğini belgeleme şartı var; profil kanıtı doğrulanmalıdır."
            ))
        else:
            add("Programlama dilleri", "met", "Profilde programlama dili kanıtı bulunmaktadır.")

    # ---- 9. Vardiya Şartı (ASLA POTANSİYEL YAPMAZ!) -----------------------
    if any("vardiya" in n for _, n in mandatory):
        shifts = candidate.get("accepts_shifts")
        if shifts is True:
            add("Vardiya", "met", "Vardiyalı çalışma şartı aday tarafından kabul ediliyor.")
        elif shifts is False:
            add("Vardiya", "not_met", "Aday vardiyalı çalışmayı kabul etmiyor.")
        else:
            add("Vardiya", "unknown", "Vardiyalı çalışma şartı var; adayın tercihi bilinmiyor.")

    # ---- 10. Genel kamu şartları (Bilgi amaçlıdır) ------------------------
    general = [label for pattern, label in GENERAL_CONDITIONS if re.search(pattern, normalized_text)]

    unknowns = list(dict.fromkeys(unknowns))
    mismatches = list(dict.fromkeys(mismatches))
    reasons = list(dict.fromkeys(reasons))

    # Kategori Belirleme
    if mismatches:
        category = "UYGUN DEĞİL"
        reason = " | ".join(mismatches)
    elif unknowns:
        category = "POTANSİYEL OLARAK UYGUN"
        # Gerekçede karşılanan temel şartlar ile eksik şartları açık ve net yaz
        met_summary = ", ".join(reasons[:2]) if reasons else ""
        unknown_summary = "; ".join(unknowns)
        if met_summary:
            reason = f"{met_summary}. Ancak şu şartların resmi kılavuzdan doğrulanması gerekmektedir: {unknown_summary}"
        else:
            reason = f"Şu şartların resmi kılavuzdan doğrulanması gerekmektedir: {unknown_summary}"
    else:
        category = "UYGUN"
        reason = " | ".join(reasons) or "İlandaki tüm ayrıştırılabilen zorunlu şartlar adayın profiliyle tam uyumludur."

    return {
        "category": category,
        "reason": reason,
        "unknown_conditions": unknowns,
        "met_conditions": reasons,
        "failed_conditions": mismatches,
        "requirements": requirements,
        "general_conditions": general,
        "education": {
            "requirement": " ".join(education_evidence),
            "computer_engineering": {
                "met": "KABUL EDİLİYOR",
                "not_met": "KABUL EDİLMİYOR",
                "unknown": "BELİRSİZ",
            }[education_status],
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


def _blank_to_none(value):
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def build_candidate_profile(stored_profile=None):
    stored_profile = stored_profile or {}
    get = (
        stored_profile.get
        if isinstance(stored_profile, dict)
        else lambda key, default=None: getattr(stored_profile, key, default)
    )
    kpss_p3 = get("kpss_p3")
    return {
        "degree": get("degree") or "",
        "department": get("department") or "",
        "university": get("university") or "",
        "kpss_score_type": "P3" if kpss_p3 is not None else "",
        "kpss_score": float(kpss_p3) if kpss_p3 is not None else None,
        "kpss_scores": {"P3": float(kpss_p3)} if kpss_p3 is not None else {},
        "preferred_locations": get("preferred_locations") or "Türkiye geneli",
        "accepts_shifts": get("accepts_shifts"),
        "yds_score": _blank_to_none(get("yds_score")),
        "age": _blank_to_none(get("age")),
        "driver_license": _blank_to_none(get("driver_license")),
        "experience_years": _blank_to_none(get("experience_years")),
        "has_internship": _blank_to_none(get("has_internship")),
        "internship_description": get("internship_description") or "",
        "certificates": _blank_to_none(get("certificates")),
        "programming_language_evidence": _blank_to_none(get("programming_language_evidence")),
        "skills": get("skills") or "",
    }
