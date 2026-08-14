#!/usr/bin/env python3
"""Phase 3 の OCR 入力に使うサンプル画像を生成する。

生成物は関数コード側（functions/phase3/sample.png）に同梱し、方式①②の
双方で同一の画像を入力として使う。

Pillow が必要なため、Layer のビルド用コンテナ内で実行する:

    finch run --rm --platform linux/arm64 \
      -v "$PWD:/work" -w /work --entrypoint /bin/sh lleval-phase3-builder \
      -c 'PYTHONPATH=/work/layers/phase3/staging/python \
          python3 scripts/make-sample-image.py functions/phase3/sample.png'

OCR の成否そのものは検証対象ではないため、ノイズのない単純な画像とする。
"""

import sys

from PIL import Image, ImageDraw, ImageFont

TEXT = "HELLO LAMBDA"
FONT_SIZE = 96
MARGIN = 40
BACKGROUND = "white"
FOREGROUND = "black"


def load_font(size):
    """スケーラブルな既定フォントを取得する。

    Pillow 10.1 以降の load_default(size=...) は TrueType ベースのフォントを
    返す。古い版では固定サイズのビットマップフォントになるため、その場合は
    後段で拡大して読み取れる大きさにする。
    """
    try:
        return ImageFont.load_default(size=size), True
    except TypeError:
        return ImageFont.load_default(), False


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "sample.png"

    font, scalable = load_font(FONT_SIZE)

    # 文字列の描画サイズを測ってから、余白を足した画像を作る
    probe = Image.new("L", (1, 1), BACKGROUND)
    bbox = ImageDraw.Draw(probe).textbbox((0, 0), TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    image = Image.new("L", (text_w + MARGIN * 2, text_h + MARGIN * 2), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN - bbox[0], MARGIN - bbox[1]), TEXT, fill=FOREGROUND, font=font)

    if not scalable:
        # ビットマップフォントしか使えない場合は拡大して可読性を確保する
        scale = max(1, FONT_SIZE // 11)
        image = image.resize(
            (image.width * scale, image.height * scale), Image.LANCZOS
        )

    image.save(out_path, "PNG", optimize=True)
    print(f"生成しました: {out_path} size={image.size} scalable_font={scalable}")


if __name__ == "__main__":
    main()
