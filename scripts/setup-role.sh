#!/usr/bin/env bash
# Lambda 実行ロールを作成する（冪等）。
# 付与するのは AWSLambdaBasicExecutionRole（CloudWatch Logs への書き込み）のみ。
set -euo pipefail
cd "$(dirname "$0")"
. ./config.sh
. ./common.sh

require_cmd aws

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}'

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  log "IAM ロールは既に存在します: $ROLE_NAME"
else
  log "IAM ロールを作成します: $ROLE_NAME"
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Execution role for lambdalayer-eval verification" \
    --tags Key=Project,Value="$PREFIX" \
    >/dev/null
fi

log "管理ポリシーをアタッチします: AWSLambdaBasicExecutionRole"
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

log "完了: $(role_arn)"
