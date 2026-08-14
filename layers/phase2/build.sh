#!/bin/sh
# Phase 2 の Layer をビルドする。
#
# Layer の構成（= Lambda 上の /opt 配下）:
#   lib/libevaldep.so    … 依存される側
#   lib/libevalmain.so   … libevaldep.so に依存する共有ライブラリ
#   bin/evaltool         … libevaldep.so にリンクする実行ファイル
#   broken/libbroken.so  … 実体のない libmissing.so に依存（検証項目 2-3 用）
#
# rpath は一切埋め込まない。実行時に LD_LIBRARY_PATH（/opt/lib を含む）で
# 解決されるかどうかが検証対象であるため。
set -eu

echo "--- gcc を導入します"
dnf install -y gcc >/dev/null

mkdir -p staging/lib staging/bin staging/broken

# リンク専用の一時領域。マウント外の /tmp に置きホスト側に残さない。
TMPLIB=/tmp/phase2-linkonly
mkdir -p "$TMPLIB"

echo "--- libevaldep.so（依存される側）をコンパイルします"
gcc -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,libevaldep.so \
    -o staging/lib/libevaldep.so \
    src/libevaldep.c

echo "--- libevalmain.so（libevaldep.so に依存）をコンパイルします"
gcc -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,libevalmain.so \
    -o staging/lib/libevalmain.so \
    src/libevalmain.c \
    -L staging/lib -levaldep

echo "--- evaltool（libevaldep.so にリンクする実行ファイル）をコンパイルします"
gcc -O2 -Wall -Wextra \
    -o staging/bin/evaltool \
    src/evaltool.c \
    -L staging/lib -levaldep
chmod 0755 staging/bin/evaltool

echo "--- libbroken.so（依存解決に失敗させる。検証項目 2-3 用）をコンパイルします"
gcc -shared -fPIC -O2 \
    -Wl,-soname,libmissing.so \
    -o "$TMPLIB/libmissing.so" \
    src/libmissing.c
gcc -shared -fPIC -O2 \
    -Wl,-soname,libbroken.so \
    -o staging/broken/libbroken.so \
    src/libbroken.c \
    -L "$TMPLIB" -lmissing
# libmissing.so は staging に含めない（= Layer に同梱しない）

echo ""
echo "--- 生成物"
find staging -type f -exec ls -l {} \;

echo ""
echo "--- DT_NEEDED（記録された依存）"
for f in staging/lib/libevalmain.so staging/bin/evaltool staging/broken/libbroken.so; do
  printf '%s:\n' "$f"
  readelf -d "$f" 2>/dev/null | grep NEEDED || true
done

echo ""
echo "--- 実行時の依存解決（ビルド環境では /opt/lib が無いため未解決になる）"
for f in staging/lib/libevalmain.so staging/bin/evaltool staging/broken/libbroken.so; do
  printf '%s:\n' "$f"
  LD_LIBRARY_PATH="$PWD/staging/lib" ldd "$f" 2>&1 | sed 's/^/  /' || true
done
