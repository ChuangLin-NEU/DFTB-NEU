#!/usr/bin/env bash
# 在 4060 上启动课堂中心（默认 0.0.0.0:8791，供公网/反向代理）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/apps${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

# 教师永久密码默认 zl303@
export DFTB_CLASS_TEACHER_PASSWORD="${DFTB_CLASS_TEACHER_PASSWORD:-zl303@}"
export DFTB_CLASS_ADMIN_SECRET="${DFTB_CLASS_ADMIN_SECRET:-$DFTB_CLASS_TEACHER_PASSWORD}"
export DFTB_CLASS_TOKEN_SECRET="${DFTB_CLASS_TOKEN_SECRET:-$DFTB_CLASS_TEACHER_PASSWORD}"

# 可选：从并列 cmats-lab/.env 导入上游 Key（按行解析，避免 source 踩坑）
if [ -f "$ROOT/../cmats-lab/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      CMATS_DEEPSEEK_API_KEY=*|CMATS_LLM_API_KEY=*|CMATS_MP_API_KEY=*|CMATS_LLM_PROVIDER=*)
        export "$line"
        ;;
    esac
  done < "$ROOT/../cmats-lab/.env" || true
  export DFTB_CLASS_DEEPSEEK_API_KEY="${DFTB_CLASS_DEEPSEEK_API_KEY:-${CMATS_DEEPSEEK_API_KEY:-}}"
  export DFTB_CLASS_LLM_API_KEY="${DFTB_CLASS_LLM_API_KEY:-${CMATS_LLM_API_KEY:-}}"
  export DFTB_CLASS_MP_API_KEY="${DFTB_CLASS_MP_API_KEY:-${CMATS_MP_API_KEY:-}}"
  export DFTB_CLASS_LLM_PROVIDER="${DFTB_CLASS_LLM_PROVIDER:-${CMATS_LLM_PROVIDER:-deepseek}}"
fi

HOST="${DFTB_CLASS_HOST:-0.0.0.0}"
PORT="${DFTB_CLASS_PORT:-8791}"
exec python3 -m uvicorn classroom_hub.main:app --host "$HOST" --port "$PORT"
