#!/usr/bin/env bash
# 教师：设置本堂学生短密码（教师永久密码默认 zl303@）
set -euo pipefail
HUB_URL="${DFTB_CLASS_PUBLIC_URL:-http://127.0.0.1:8791}"
TEACHER="${DFTB_CLASS_TEACHER_PASSWORD:-zl303@}"
STUDENT_CODE="${1:?用法: $0 <本堂学生短密码> [有效天数]}"
DAYS="${2:-30}"
curl -fsS -X POST "$HUB_URL/teacher/gate" \
  -H "Content-Type: application/json" \
  -H "X-Teacher-Password: $TEACHER" \
  -d "{\"student_password\":\"$STUDENT_CODE\",\"session_days\":$DAYS}" | python3 -m json.tool
echo
echo "请告诉学生本堂口令：$STUDENT_CODE"
echo "学生只需在软件「进入」页输入该口令。"
