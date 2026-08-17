#!/usr/bin/env bash
# 开发启动本地 API + 课堂 UI
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/apps/api:$ROOT/engines/dftb_agent${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT/apps/api"
exec python3 -m uvicorn dftbneu.main:app --host 127.0.0.1 --port "${DFTB_NEU_PORT:-8765}" "$@"
