#!/bin/sh
# API'yi yerelde başlatır. İlk çalıştırmada rastgele bir erişim anahtarı üretip .env dosyasına yazar.
set -e
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "$CAREERPILOT_ACCESS_TOKEN" ]; then
  CAREERPILOT_ACCESS_TOKEN="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(24))')"
  export CAREERPILOT_ACCESS_TOKEN
  printf 'CAREERPILOT_ACCESS_TOKEN=%s\n' "$CAREERPILOT_ACCESS_TOKEN" >> .env
  echo "Yeni erişim anahtarı üretildi ve .env dosyasına yazıldı. Arayüzde bu anahtarla giriş yapın."
fi

exec "$PYTHON" -m uvicorn backend.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
