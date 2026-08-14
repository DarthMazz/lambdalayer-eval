#!/bin/sh
# Phase 3 の Layer をビルドする。
#
# AL2023 のリポジトリには tesseract / leptonica が存在しないため、
# 公式アップストリームのソースからビルドする（要件定義 §9-2 案 B）。
#
# Layer の構成（= Lambda 上の /opt 配下）:
#   bin/tesseract          … 実行ファイル（方式② pytesseract で使用）
#   lib/libtesseract.so*   … 本体。方式①② の双方で必要
#   lib/libleptonica.so*   … 画像処理ライブラリ
#   lib/（その他）          … 再帰的に洗い出した非 glibc 依存
#   tessdata/eng.traineddata
#   python/                … pytesseract と Pillow（方式② で使用）
set -eu

# --- 固定するバージョン（再現性のため）--------------------------------
LEPT_VER=1.87.0
TESS_VER=5.5.3
TESSDATA_REPO=tessdata_fast   # 最小構成。精度より Layer サイズを優先
TESSDATA_LANG=eng

PREFIX=/tmp/tessprefix
SRC=/tmp/tesssrc
JOBS="$(nproc)"

# glibc 本体が提供するものは同梱しない。
# Lambda 実行環境に必ず存在し、差し替えるとかえって危険なため。
EXCLUDE_PATTERN='^(libc|libm|libdl|libpthread|librt|libresolv|libutil)\.so|^ld-linux|^linux-vdso'

mkdir -p "$SRC" "$PREFIX" staging/lib staging/bin staging/tessdata staging/python

export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$PREFIX/lib64/pkgconfig"
export LD_LIBRARY_PATH="$PREFIX/lib:$PREFIX/lib64"

# --- 1. Leptonica -----------------------------------------------------
# リリース tarball に同梱の configure を使う（CMake は当環境で
# Threads::Threads の解決に失敗するため）。
echo "=== Leptonica ${LEPT_VER} を取得・ビルドします"
cd "$SRC"
curl -sSL -o leptonica.tar.gz \
  "https://github.com/DanBloomberg/leptonica/releases/download/${LEPT_VER}/leptonica-${LEPT_VER}.tar.gz"
tar xzf leptonica.tar.gz
cd "leptonica-${LEPT_VER}"

# 付属プログラムは Layer に不要。giflib / openjpeg は未導入のため自動的に無効になる。
./configure \
  --prefix="$PREFIX" \
  --enable-shared \
  --disable-static \
  --disable-programs \
  >/dev/null
make -j "$JOBS" >/dev/null
make install >/dev/null
echo "    完了: $(ls "$PREFIX"/lib/liblept*.so* 2>/dev/null | head -1)"

# --- 2. Tesseract -----------------------------------------------------
# GitHub のタグ tarball には configure が含まれないため autogen.sh を実行する。
echo "=== Tesseract ${TESS_VER} を取得・ビルドします（数分かかります）"
cd "$SRC"
curl -sSL -o tesseract.tar.gz \
  "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/${TESS_VER}.tar.gz"
tar xzf tesseract.tar.gz
cd "tesseract-${TESS_VER}"

./autogen.sh >/dev/null
# 学習ツールは不要。Layer サイズと依存を抑える。
./configure \
  --prefix="$PREFIX" \
  --enable-shared \
  --disable-static \
  --disable-doc \
  >/dev/null
make -j "$JOBS" >/dev/null
make install >/dev/null
echo "    完了: $(ls "$PREFIX"/lib/libtesseract*.so* 2>/dev/null | head -1)"

cd /work

# --- 3. 成果物を staging へ配置 ----------------------------------------
echo "=== 成果物を配置します"
cp -a "$PREFIX/bin/tesseract" staging/bin/
chmod 0755 staging/bin/tesseract

for d in "$PREFIX/lib" "$PREFIX/lib64"; do
  [ -d "$d" ] || continue
  find "$d" -maxdepth 1 -name '*.so*' -exec cp -a {} staging/lib/ \;
done

# --- 4. 依存ライブラリの再帰的な洗い出し --------------------------------
# Phase 2 で確認したとおり、依存が 1 つでも欠けると
# "cannot open shared object file" でロードに失敗する。
# 収束するまで繰り返し、非 glibc 依存をすべて同梱する。
echo "=== 依存ライブラリを洗い出します"
i=1
while [ "$i" -le 6 ]; do
  before="$(find staging/lib -name '*.so*' | wc -l)"
  for f in staging/bin/tesseract staging/lib/*.so*; do
    [ -e "$f" ] || continue
    LD_LIBRARY_PATH="/work/staging/lib:$PREFIX/lib:$PREFIX/lib64" \
      ldd "$f" 2>/dev/null | sed -n 's/.*=> \(\/[^ ]*\).*/\1/p'
  done | sort -u > /tmp/deps.txt

  while read -r lib; do
    [ -f "$lib" ] || continue
    base="$(basename "$lib")"
    echo "$base" | grep -Eq "$EXCLUDE_PATTERN" && continue
    [ -e "staging/lib/$base" ] && continue
    cp -L "$lib" "staging/lib/$base"
    echo "    + $base"
  done < /tmp/deps.txt

  after="$(find staging/lib -name '*.so*' | wc -l)"
  [ "$before" = "$after" ] && break
  i=$((i + 1))
done

# --- 5. 言語データ -----------------------------------------------------
echo "=== 言語データ (${TESSDATA_REPO}/${TESSDATA_LANG}) を取得します"
curl -sSL -o "staging/tessdata/${TESSDATA_LANG}.traineddata" \
  "https://github.com/tesseract-ocr/${TESSDATA_REPO}/raw/main/${TESSDATA_LANG}.traineddata"
ls -l staging/tessdata/

# --- 6. Python パッケージ ----------------------------------------------
# Lambda 実行環境と同一のコンテナ内で入れることで、
# aarch64 向けの正しい wheel が取得される（macOS 上で入れると動作しない）。
echo "=== Python パッケージを導入します"
python3 -m pip install --quiet --no-compile --target staging/python \
  pytesseract Pillow
find staging/python -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find staging/python -maxdepth 1 -mindepth 1 -exec basename {} \; | sort | sed 's/^/    /'

# --- 7. strip によるサイズ削減 -----------------------------------------
echo "=== strip を適用します"
size_before="$(du -sk staging | awk '{print $1}')"
find staging/lib staging/bin -type f \( -name '*.so*' -o -name 'tesseract' \) \
  -exec strip --strip-unneeded {} \; 2>/dev/null || true
size_after="$(du -sk staging | awk '{print $1}')"
echo "    strip 前: ${size_before} KB / strip 後: ${size_after} KB"

# --- 8. 検証情報の出力 -------------------------------------------------
echo ""
echo "=== 同梱したライブラリ"
ls -l staging/lib/ | sed 's/^/    /'

echo ""
echo "=== tesseract の依存解決（/work/staging/lib を /opt/lib に見立てて確認）"
LD_LIBRARY_PATH=/work/staging/lib ldd staging/bin/tesseract | sed 's/^/    /'

echo ""
echo "=== libtesseract の依存解決"
TESS_SO="$(find staging/lib -name 'libtesseract.so*' ! -type l | head -1)"
LD_LIBRARY_PATH=/work/staging/lib ldd "$TESS_SO" | sed 's/^/    /'

echo ""
echo "=== 未解決の依存がないことの確認"
if LD_LIBRARY_PATH=/work/staging/lib ldd staging/bin/tesseract staging/lib/*.so* 2>/dev/null \
   | grep -q "not found"; then
  echo "    [NG] 未解決の依存があります"
  LD_LIBRARY_PATH=/work/staging/lib ldd staging/bin/tesseract staging/lib/*.so* 2>/dev/null \
    | grep "not found" | sed 's/^/      /'
  exit 1
fi
echo "    [OK] すべて解決されています"

echo ""
echo "=== 構成別のサイズ"
du -sh staging/* | sed 's/^/    /'
echo "    ---"
du -sh staging | sed 's/^/    合計 /'
