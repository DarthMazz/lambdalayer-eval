#!/usr/bin/env bash
# 指定フェーズの関数を invoke し、レスポンスと実行ログを表示する。
# 使い方: ./invoke.sh <phase> ['{"json":"payload"}']
set -euo pipefail
cd "$(dirname "$0")"
. ./config.sh
. ./common.sh

PHASE="${1:-}"
require_phase "$PHASE"
PAYLOAD="${2:-}"
[ -n "$PAYLOAD" ] || PAYLOAD='{}'
require_cmd aws

FN_NAME="$(function_name "$PHASE")"
OUT="${BUILD_OUT_DIR}/phase${PHASE}-response.json"
mkdir -p "$BUILD_OUT_DIR"

log "invoke します: ${FN_NAME}"
LOG_B64="$(aws lambda invoke \
  --function-name "$FN_NAME" \
  --cli-binary-format raw-in-base64-out \
  --payload "$PAYLOAD" \
  --log-type Tail \
  --query LogResult --output text \
  "$OUT")"

printf '\n\033[1;36m--- 実行ログ ---------------------------------------------\033[0m\n' >&2
printf '%s' "$LOG_B64" | base64 --decode >&2

printf '\n\033[1;36m--- レスポンス -------------------------------------------\033[0m\n' >&2
if command -v jq >/dev/null 2>&1; then
  jq . "$OUT"
else
  cat "$OUT"; echo
fi

printf '\n\033[1;36m----------------------------------------------------------\033[0m\n' >&2
log "レスポンスの保存先: ${OUT}"
