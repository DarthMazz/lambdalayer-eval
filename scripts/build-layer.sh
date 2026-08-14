#!/usr/bin/env bash
# 指定フェーズの Layer をビルドして .build/phase<N>-layer.zip を生成する。
#
# 各フェーズは layers/phase<N>/build.sh を持つ。build.sh は
# Lambda 実行環境と同一のコンテナ内で /work（= layers/phase<N>）を作業ディレクトリとして実行され、
# ./staging/ 配下に Layer の中身（lib/ bin/ python/ tessdata/ など）を配置する責務を持つ。
#
# 使い方: ./build-layer.sh <phase>
set -euo pipefail
cd "$(dirname "$0")"
. ./config.sh
. ./common.sh

PHASE="${1:-}"
require_phase "$PHASE"
require_cmd zip "$CONTAINER_CMD"

LAYER_SRC="${LAYERS_DIR}/phase${PHASE}"
BUILD_SCRIPT="${LAYER_SRC}/build.sh"
STAGING="${LAYER_SRC}/staging"
ZIP_PATH="${BUILD_OUT_DIR}/phase${PHASE}-layer.zip"

if [ ! -f "$BUILD_SCRIPT" ]; then
  log "phase${PHASE} には Layer がありません（${BUILD_SCRIPT} が存在しない）。スキップします。"
  exit 0
fi

log "Layer をビルドします: phase${PHASE}"
rm -rf "$STAGING"
mkdir -p "$STAGING" "$BUILD_OUT_DIR"

# フェーズ固有の Containerfile があれば、それをビルド用イメージとして使う。
# ビルド依存の導入をイメージ層にキャッシュし、反復ビルドを速くするため。
if [ -f "${LAYER_SRC}/Containerfile" ]; then
  BUILD_IMAGE="${PREFIX}-phase${PHASE}-builder"
  export BUILD_IMAGE
  log "ビルド用イメージを作成します: ${BUILD_IMAGE}"
  "$CONTAINER_CMD" build \
    --platform "$BUILD_PLATFORM" \
    -t "$BUILD_IMAGE" \
    -f "${LAYER_SRC}/Containerfile" \
    "$LAYER_SRC"
fi

# Lambda 実行環境と同一のコンテナ内でビルドする（ELF/aarch64 を得るため）
run_in_builder "$LAYER_SRC" "set -eu; sh ./build.sh"

[ -n "$(ls -A "$STAGING" 2>/dev/null || true)" ] \
  || die "staging/ が空です。layers/phase${PHASE}/build.sh の出力先を確認してください。"

log "生成物を検証します"
find "$STAGING" -name '*.so*' -type f | while read -r so; do
  desc="$(file -b "$so")"
  case "$desc" in
    *"ELF 64-bit"*"aarch64"*) printf '  [OK] %s\n' "${so#"$STAGING"/}" >&2 ;;
    *) die "aarch64 の ELF ではありません: ${so#"$STAGING"/} => ${desc}" ;;
  esac
done

log "ZIP を作成します: ${ZIP_PATH}"
rm -f "$ZIP_PATH"
( cd "$STAGING" && zip -q -r -y "$ZIP_PATH" . )

UNZIPPED=$(find "$STAGING" -type f -exec stat -f %z {} + | awk '{s+=$1} END {print s+0}')
log "完了  zip: $(stat -f %z "$ZIP_PATH") bytes / 解凍後: ${UNZIPPED} bytes"
