# CareerPilot TR API — Chromium dahil, her ortamda aynı çalışan imaj.
# Kariyer Kapısı ve İlan.gov.tr taraması bir tarayıcı gerektirir; bu imaj tarayıcıyı ve
# sistem kitaplıklarını sürüm uyumlu biçimde kurar (Playwright'ın kendi kurulum komutuyla).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright TZ=Europe/Istanbul

WORKDIR /app
COPY requirements.txt .
# libatomic1: Playwright'ın sürücüsü (node) ince imajda bu kitaplık olmadan başlamaz.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend ./backend
# Boş üretim veritabanını bir kez doldurmak için son SQLite dosyası (CAREERPILOT_DB_SEED_FROM_REPO=true).
COPY careerpilot.db ./careerpilot.db

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
