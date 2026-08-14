#!/usr/bin/env bash
# 検証で作成した AWS リソースを削除する。
#
#   ./cleanup.sh            … Lambda 関数と Layer の全バージョンを削除
#   ./cleanup.sh --all      … 上記に加えて IAM ロールと CloudWatch ロググループも削除
#
# プレフィックス "lleval" が付いたリソースのみを対象とする。
set -euo pipefail
cd "$(dirname "$0")"
. ./config.sh
. ./common.sh

require_cmd aws
ALL="${1:-}"

log "削除対象を確認します（プレフィックス: ${PREFIX}）"

# --- Lambda 関数 -------------------------------------------------------
FUNCS="$(aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName, \`${PREFIX}-\`)].FunctionName" \
  --output text)"
if [ -n "$FUNCS" ]; then
  for f in $FUNCS; do
    log "関数を削除します: $f"
    aws lambda delete-function --function-name "$f"
  done
else
  log "削除対象の関数はありません"
fi

# --- Layer（全バージョン） ---------------------------------------------
LAYERS="$(aws lambda list-layers \
  --query "Layers[?starts_with(LayerName, \`${PREFIX}-\`)].LayerName" \
  --output text)"
if [ -n "$LAYERS" ]; then
  for l in $LAYERS; do
    VERSIONS="$(aws lambda list-layer-versions --layer-name "$l" \
      --query 'LayerVersions[].Version' --output text)"
    for v in $VERSIONS; do
      log "Layer を削除します: ${l}:${v}"
      aws lambda delete-layer-version --layer-name "$l" --version-number "$v"
    done
  done
else
  log "削除対象の Layer はありません"
fi

if [ "$ALL" = "--all" ]; then
  # --- CloudWatch ロググループ -----------------------------------------
  GROUPS="$(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/lambda/${PREFIX}-" \
    --query 'logGroups[].logGroupName' --output text)"
  for g in $GROUPS; do
    log "ロググループを削除します: $g"
    aws logs delete-log-group --log-group-name "$g"
  done

  # --- IAM ロール -------------------------------------------------------
  if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    POLICIES="$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
      --query 'AttachedPolicies[].PolicyArn' --output text)"
    for p in $POLICIES; do
      log "ポリシーをデタッチします: $p"
      aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$p"
    done
    log "IAM ロールを削除します: $ROLE_NAME"
    aws iam delete-role --role-name "$ROLE_NAME"
  fi
else
  log "IAM ロールとロググループは残しています（削除するには --all を付けてください）"
fi

log "クリーンアップ完了"
