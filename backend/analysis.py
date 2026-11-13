from collections import Counter
import re

# Initial transparent dictionary. Later we will add synonym mapping and LLM-assisted extraction.
SKILL_ALIASES = {
    "python": ["python"],
    "sql": ["sql", "structured query language"],
    "power bi": ["power bi", "powerbi"],
    "tableau": ["tableau"],
    "excel": ["excel", "microsoft excel"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "postgresql": ["postgresql", "postgres"],
    "mysql": ["mysql"],
    "etl": ["etl", "extract transform load"],
    "airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt", "data build tool"],
    "docker": ["docker"],
    "git": ["git", "github"],
    "fastapi": ["fastapi"],
    "rest api": ["rest api", "restful api"],
    "machine learning": ["machine learning", "makine öğrenmesi"],
    "deep learning": ["deep learning", "derin öğrenme"],
    "tensorflow": ["tensorflow", "keras"],
    "pytorch": ["pytorch"],
    "llm": ["llm", "large language model", "büyük dil modeli"],
    "rag": ["rag", "retrieval augmented generation"],
    "ai agents": ["ai agent", "ai agents", "agentic", "yapay zekâ ajan", "yapay zeka ajan"],
    "n8n": ["n8n"],
    "flutter": ["flutter", "dart"],
    "aws": ["aws", "amazon web services"],
    "azure": ["azure"],
    "gcp": ["gcp", "google cloud"],
}


def extract_skills(text: str) -> list[str]:
    normalized = (text or "").casefold()
    found = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            # Avoid matching short skills inside longer words.
            pattern = rf"(?<![a-z0-9+#]){re.escape(alias.casefold())}(?![a-z0-9+#])"
            if re.search(pattern, normalized):
                found.append(canonical)
                break
    return found


def skill_frequency(jobs: list[dict]) -> list[dict]:
    """Count how many selected job ads mention each skill at least once."""
    counts: Counter[str] = Counter()
    for job in jobs:
        text = " ".join(str(job.get(key, "") or "") for key in ("skills", "description", "title"))
        for skill in extract_skills(text):
            counts[skill] += 1
    total = len(jobs)
    return [
        {"skill": skill, "count": count, "total": total, "percentage": round(count * 100 / total, 1) if total else 0.0}
        for skill, count in counts.most_common()
    ]


def check_public_score_fit(job: dict, profile: dict) -> str:
    """A preliminary score-only check, not a full legal eligibility decision."""
    min_score = job.get("kpss_min_score")
    candidate_score = profile.get("kpss_p3")
    score_type = (job.get("kpss_score_type") or "").strip().upper()
    if min_score is None or not score_type:
        return "KPSS koşulu manuel kontrol edilmeli"
    if score_type != "P3":
        return "Puan türü P3 değil; manuel kontrol gerekli"
    if candidate_score is None:
        return "Adayın P3 puanı profile girilmemiş"
    if candidate_score >= float(min_score):
        return "Puan şartı karşılanıyor; diğer tüm şartlar kontrol edilmeli"
    return "Puan şartı karşılanmıyor"
