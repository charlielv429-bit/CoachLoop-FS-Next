#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python || ! -d frontend/node_modules ]]; then
  echo '请先执行 bash scripts/setup.sh'; exit 1
fi
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 &
backend_pid=$!
cleanup() { kill "$backend_pid" "${frontend_pid:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd frontend && npm run dev -- --host 127.0.0.1) &
frontend_pid=$!
wait "$backend_pid" "$frontend_pid"
