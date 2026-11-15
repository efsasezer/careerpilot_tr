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

if [ -z "$CAREERPILOT_ACCESS_TOKEN" ]; then
  echo "Erişim anahtarı tanımlı değil: API yalnızca bu bilgisayardan gelen isteklere anahtarsız yanıt verir."
fi

exec "$PYTHON" -m uvicorn backend.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
