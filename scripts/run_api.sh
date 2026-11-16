#!/bin/sh
# API'yi yerelde başlatır; varsa .env dosyasındaki ayarları yükler.
set -e
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "$CAREERPILOT_PASSWORD" ] || [ -z "$CAREERPILOT_SESSION_SECRET" ]; then
  echo "UYARI: .env dosyasında CAREERPILOT_PASSWORD ve CAREERPILOT_SESSION_SECRET tanımlı değil; giriş yapılamaz."
  echo "       .env.example dosyasını .env olarak kopyalayıp doldurun."
fi

exec "$PYTHON" -m uvicorn backend.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
