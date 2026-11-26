#!/bin/sh
# Türkiye'deki bu bilgisayarda taramayı 6 saatte bir kendiliğinden çalıştırır (macOS launchd).
# Yalnızca Türkiye'den erişilebilen kaynakları (SBB, Kariyer Kapısı, Yerel Yönetimler) üretim
# veritabanına yazmak içindir. .env dosyasında DATABASE_URL tanımlı olmalıdır.
#   Kur:     sh scripts/tarayici_kur.sh
#   Kaldır:  sh scripts/tarayici_kur.sh kaldir
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="tr.careerpilot.tarayici"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "kaldir" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Zamanlanmış tarama kaldırıldı."
  exit 0
fi

[ -x "$ROOT/.venv/bin/python" ] || { echo "Önce sanal ortamı kurun: python -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
grep -q '^DATABASE_URL=' "$ROOT/.env" 2>/dev/null || { echo ".env dosyasında DATABASE_URL tanımlı değil; üretim veritabanının adresini ekleyin."; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data"
cat > "$PLIST" <<PLIST_END
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>set -a; . ./.env; set +a; exec ./.venv/bin/python -m backend.sync</string>
  </array>
  <key>StartInterval</key><integer>21600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/tarayici.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/tarayici.log</string>
</dict></plist>
PLIST_END
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Zamanlanmış tarama kuruldu: 6 saatte bir çalışır. Günlük: $ROOT/data/tarayici.log"
