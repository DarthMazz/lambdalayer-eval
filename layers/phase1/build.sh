#!/bin/sh
# Phase 1 の Layer をビルドする。
#
# このスクリプトは scripts/build-layer.sh から、Lambda 実行環境と同一の
# コンテナ内で実行される（作業ディレクトリ = /work = layers/phase1）。
# 成果物は ./staging/ 配下に置くこと。そこが Layer の /opt に相当する。
set -eu

echo "--- gcc を導入します（ベースイメージに未同梱のため）"
dnf install -y gcc >/dev/null

mkdir -p staging/lib

echo "--- libeval.so をコンパイルします"
gcc -shared -fPIC -O2 \
    -Wall -Wextra \
    -o staging/lib/libeval.so \
    src/libeval.c

echo "--- 生成物"
ls -l staging/lib/
file staging/lib/libeval.so 2>/dev/null || true

# 依存を持たないことを確認する（Phase 1 の前提）
echo "--- 依存ライブラリ"
ldd staging/lib/libeval.so || true

echo "--- 公開シンボル"
nm -D --defined-only staging/lib/libeval.so 2>/dev/null | grep -E ' T ' || true
