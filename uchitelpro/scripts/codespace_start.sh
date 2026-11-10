#!/usr/bin/env bash
# Запуск «УчительPRO» в GitHub Codespaces: сервер + публичный порт + QR-код.
set -u
cd "$(dirname "$0")/.."
PORT=8765
DATA="$HOME/.uchitelpro"
mkdir -p "$DATA"

pkill -f "run.py --host" 2>/dev/null
nohup python run.py --host 0.0.0.0 --port "$PORT" --no-open --data "$DATA" > "$DATA/server.log" 2>&1 &

for i in $(seq 1 30); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/login" && break
  sleep 1
done

gh codespace ports visibility "$PORT:public" -c "${CODESPACE_NAME:-}" >/dev/null 2>&1 \
  || echo "! Порт не стал публичным автоматически: вкладка «Порты» → правый клик по $PORT → «Видимость порта» → Public"

PORT="$PORT" python scripts/qr_public.py
