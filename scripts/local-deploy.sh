#!/usr/bin/env bash
# Local deploy: API :8000 + Web :3000 (personal / SQLite)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p data logs
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
if [[ ! -f apps/web/.env.local ]]; then
  cp apps/web/.env.example apps/web/.env.local
  echo "Created apps/web/.env.local"
fi

python3 -m pip install -e ".[dev]" -q
(cd apps/web && npm install --silent)

# Stop previous local-deploy PIDs if present
if [[ -f logs/api.pid ]]; then kill "$(cat logs/api.pid)" 2>/dev/null || true; fi
if [[ -f logs/web.pid ]]; then kill "$(cat logs/web.pid)" 2>/dev/null || true; fi

echo "Starting API on 0.0.0.0:8000 ..."
nohup env PYTHONPATH=packages:apps \
  uvicorn api.main:app --host 0.0.0.0 --port 8000 \
  > logs/api.log 2>&1 &
echo $! > logs/api.pid

echo "Starting Web on 0.0.0.0:3000 ..."
nohup npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 3000 \
  > logs/web.log 2>&1 &
echo $! > logs/web.pid

for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/healthz >/dev/null; then
    break
  fi
  sleep 1
done

curl -sf http://127.0.0.1:8000/healthz | tee logs/healthz.json
echo
curl -sf http://127.0.0.1:8000/v1/meta | tee logs/meta.json
echo
echo "API PID $(cat logs/api.pid)  WEB PID $(cat logs/web.pid)"
echo "Open http://127.0.0.1:3000  (API http://127.0.0.1:8000)"
