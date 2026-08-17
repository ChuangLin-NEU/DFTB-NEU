#!/usr/bin/env bash
# DFTB Neu worker — 仅使用 ~/.dftb-neu 隔离环境
set -euo pipefail
JOB_ID="${1:?job_id}"
BASE="${DFTB_NEU_JOBS:-$HOME/.dftb-neu/jobs}"
JD="$BASE/$JOB_ID"
export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$HOME/.dftb-neu/bin:$PATH"
cd "$JD"
echo running > status
dftb+ > dftb.log 2>&1
rc=$?
if [ $rc -eq 0 ]; then echo done > status; else echo error > status; fi
echo $rc > exit_code
exit $rc
