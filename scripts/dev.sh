#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo '请先执行 bash scripts/setup.sh'; exit 1
fi
# Read only the port; preserve process overrides and existing backend/.env.
BACKEND_PORT="${BACKEND_PORT:-$(.venv/bin/python -c "from dotenv import dotenv_values; print(dotenv_values('backend/.env').get('BACKEND_PORT') or '8000')")}"
export BACKEND_PORT
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT" &
backend_pid=$!
cleanup() { kill "$backend_pid" "${frontend_pid:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd frontend && npm run dev -- --host 127.0.0.1) &
frontend_pid=$!
wait "$backend_pid" "$frontend_pid"
