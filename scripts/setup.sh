#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock.txt
(cd frontend && npm ci)
if [[ ! -f backend/.env ]]; then cp backend/.env.example backend/.env; fi
echo '安装完成。请在 backend/.env 中设置模型凭据，然后运行 bash scripts/dev.sh'
