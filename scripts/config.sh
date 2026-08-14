#!/usr/bin/env bash
# 検証全体で共有する設定値。各スクリプトから source される。

# --- AWS ---------------------------------------------------------------
export AWS_REGION="${AWS_REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

# --- 命名 --------------------------------------------------------------
# 作成する全リソースにこのプレフィックスを付け、cleanup.sh で一括削除できるようにする。
export PREFIX="lleval"
export ROLE_NAME="${PREFIX}-lambda-role"

# --- Lambda ------------------------------------------------------------
export LAMBDA_RUNTIME="python3.13"
export LAMBDA_ARCH="arm64"
export LAMBDA_HANDLER="handler.lambda_handler"
export LAMBDA_MEMORY="512"
export LAMBDA_TIMEOUT="30"

# --- ビルド環境 --------------------------------------------------------
# Lambda 実行環境と同一のイメージを使い、ELF(aarch64) を生成する。
export CONTAINER_CMD="${CONTAINER_CMD:-finch}"
export BUILD_IMAGE="${BUILD_IMAGE:-public.ecr.aws/lambda/python:3.13}"
export BUILD_PLATFORM="linux/arm64"

# --- パス --------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT
export LAYERS_DIR="${REPO_ROOT}/layers"
export FUNCTIONS_DIR="${REPO_ROOT}/functions"
export BUILD_OUT_DIR="${REPO_ROOT}/.build"
