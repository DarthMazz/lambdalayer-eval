#!/usr/bin/env bash
# 指定フェーズの Layer を発行し、Lambda 関数を作成／更新する（冪等）。
# 使い方: ./deploy.sh <phase>
set -euo pipefail
cd "$(dirname "$0")"
. ./config.sh
. ./common.sh

PHASE="${1:-}"
require_phase "$PHASE"
require_cmd aws zip

FN_SRC="${FUNCTIONS_DIR}/phase${PHASE}"
[ -d "$FN_SRC" ] || die "関数コードが見つかりません: $FN_SRC"

FN_NAME="$(function_name "$PHASE")"
LAYER_NAME="$(layer_name "$PHASE")"
LAYER_ZIP="${BUILD_OUT_DIR}/phase${PHASE}-layer.zip"
FN_ZIP="${BUILD_OUT_DIR}/phase${PHASE}-fn.zip"

mkdir -p "$BUILD_OUT_DIR"

# --- Layer の発行 ------------------------------------------------------
LAYER_ARN=""
if [ -f "$LAYER_ZIP" ]; then
  log "Layer を発行します: ${LAYER_NAME}"
  LAYER_ARN="$(aws lambda publish-layer-version \
    --layer-name "$LAYER_NAME" \
    --description "lambdalayer-eval phase${PHASE}" \
    --zip-file "fileb://${LAYER_ZIP}" \
    --compatible-runtimes "$LAMBDA_RUNTIME" \
    --compatible-architectures "$LAMBDA_ARCH" \
    --query LayerVersionArn --output text)"
  log "発行しました: ${LAYER_ARN}"
else
  log "Layer ZIP がないため Layer なしでデプロイします（phase${PHASE}）"
fi

# --- 関数コードの ZIP 化 -----------------------------------------------
log "関数コードを ZIP 化します: ${FN_SRC}"
rm -f "$FN_ZIP"
( cd "$FN_SRC" && zip -q -r -y "$FN_ZIP" . -x '__pycache__/*' )

# --- 関数の作成／更新 --------------------------------------------------
if function_exists "$FN_NAME"; then
  log "関数を更新します: ${FN_NAME}"
  aws lambda update-function-code \
    --function-name "$FN_NAME" \
    --zip-file "fileb://${FN_ZIP}" >/dev/null
  wait_function_ready "$FN_NAME"

  set -- --function-name "$FN_NAME" \
         --handler "$LAMBDA_HANDLER" \
         --memory-size "$LAMBDA_MEMORY" \
         --timeout "$LAMBDA_TIMEOUT"
  if [ -n "$LAYER_ARN" ]; then
    set -- "$@" --layers "$LAYER_ARN"
  fi
  aws lambda update-function-configuration "$@" >/dev/null
  wait_function_ready "$FN_NAME"
else
  log "関数を作成します: ${FN_NAME}"
  set -- --function-name "$FN_NAME" \
         --runtime "$LAMBDA_RUNTIME" \
         --architectures "$LAMBDA_ARCH" \
         --role "$(role_arn)" \
         --handler "$LAMBDA_HANDLER" \
         --zip-file "fileb://${FN_ZIP}" \
         --memory-size "$LAMBDA_MEMORY" \
         --timeout "$LAMBDA_TIMEOUT" \
         --tags "Project=${PREFIX}"
  if [ -n "$LAYER_ARN" ]; then
    set -- "$@" --layers "$LAYER_ARN"
  fi

  # IAM ロール作成直後は伝播待ちで InvalidParameterValueException になることがあるため再試行する
  i=1
  until aws lambda create-function "$@" >/dev/null 2>/tmp/lleval-create-err; do
    if [ "$i" -ge 10 ]; then
      cat /tmp/lleval-create-err >&2
      die "関数の作成に失敗しました: ${FN_NAME}"
    fi
    warn "作成に失敗しました。IAM ロールの伝播待ちの可能性があるため再試行します (${i}/10)"
    i=$((i + 1))
    sleep 5
  done
  aws lambda wait function-active-v2 --function-name "$FN_NAME"
fi

log "デプロイ完了: ${FN_NAME}"
