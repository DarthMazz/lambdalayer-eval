"""Phase 3: Tesseract を Layer から利用する（本番想定）.

同一の Layer 上で 2 つの方式を実行し、比較する。

  方式① ctypes      : libtesseract.so の C API を直接呼ぶ。Python 依存なし
  方式② pytesseract : /opt/bin/tesseract を subprocess 経由で呼ぶ

要件定義の検証項目 3-3 〜 3-13 に対応する。
"""

import ctypes
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

LIB_DIR = "/opt/lib"
BIN_DIR = "/opt/bin"
TESSDATA_DIR = "/opt/tessdata"
TOOL = os.path.join(BIN_DIR, "tesseract")
IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.png")

LANG = "eng"
EXPECTED_TEXT = "HELLO LAMBDA"
REPEAT = 3  # 3-11 の性能比較で各方式を実行する回数


def check(checks, item, description):
    def runner(fn):
        entry = {"item": item, "description": description}
        started = time.perf_counter()
        try:
            entry["result"] = fn()
            entry["ok"] = True
        except Exception as e:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        checks.append(entry)
        return entry

    return runner


def _find_lib(*patterns):
    """Layer 内のライブラリをパターンで探す。

    cmake が生成する実体名（libtesseract.so.5.5.3 等）は版によって変わるため、
    ファイル名を決め打ちにしない。
    """
    for pattern in patterns:
        found = sorted(glob.glob(os.path.join(LIB_DIR, pattern)))
        if found:
            # シンボリックリンク（libtesseract.so）を優先する
            found.sort(key=lambda p: (not os.path.islink(p), len(p)))
            return found[0]
    raise FileNotFoundError(f"該当するライブラリが見つかりません: {patterns}")


def _normalize(text):
    return " ".join(text.split()).strip()


def _matches_expected(text):
    return _normalize(text).upper() == EXPECTED_TEXT.upper()


# ---------------------------------------------------------------------
# 方式① ctypes による C API 直接呼び出し
# ---------------------------------------------------------------------
class CtypesTesseract:
    def __init__(self):
        self.lib_path = _find_lib("libtesseract.so", "libtesseract.so.*")
        self.lib = ctypes.CDLL(self.lib_path)
        self._declare()
        self.lept_path = None
        self.lept = None

    def _declare(self):
        """argtypes / restype を明示的に宣言する。

        Phase 1 で実測したとおり、restype 未宣言だと 64bit ポインタが
        int へ切り詰められ、例外も出ずに不正な値が返る。
        """
        lib = self.lib
        lib.TessVersion.argtypes = []
        lib.TessVersion.restype = ctypes.c_char_p

        lib.TessBaseAPICreate.argtypes = []
        lib.TessBaseAPICreate.restype = ctypes.c_void_p

        lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.TessBaseAPIInit3.restype = ctypes.c_int

        lib.TessBaseAPISetImage.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ]
        lib.TessBaseAPISetImage.restype = None

        lib.TessBaseAPISetImage2.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.TessBaseAPISetImage2.restype = None

        # GetUTF8Text が返すポインタは TessDeleteText で解放する必要があるため、
        # c_char_p ではなく c_void_p で受けてポインタ値を保持する。
        lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
        lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p

        lib.TessDeleteText.argtypes = [ctypes.c_void_p]
        lib.TessDeleteText.restype = None

        lib.TessBaseAPIEnd.argtypes = [ctypes.c_void_p]
        lib.TessBaseAPIEnd.restype = None

        lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
        lib.TessBaseAPIDelete.restype = None

    def load_leptonica(self):
        self.lept_path = _find_lib("libleptonica.so", "libleptonica.so.*", "liblept.so*")
        self.lept = ctypes.CDLL(self.lept_path)
        self.lept.pixRead.argtypes = [ctypes.c_char_p]
        self.lept.pixRead.restype = ctypes.c_void_p
        self.lept.pixDestroy.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self.lept.pixDestroy.restype = None
        return self.lept_path

    def version(self):
        return self.lib.TessVersion().decode("utf-8")

    def create_and_init(self):
        handle = self.lib.TessBaseAPICreate()
        if not handle:
            raise RuntimeError("TessBaseAPICreate が NULL を返しました")
        rc = self.lib.TessBaseAPIInit3(
            handle, TESSDATA_DIR.encode("utf-8"), LANG.encode("utf-8")
        )
        if rc != 0:
            self.lib.TessBaseAPIDelete(handle)
            raise RuntimeError(f"TessBaseAPIInit3 が {rc} を返しました（0 が成功）")
        return handle

    def ocr(self, handle, image_path):
        """leptonica の pixRead で画像を読み、OCR を実行する。"""
        pix = self.lept.pixRead(image_path.encode("utf-8"))
        if not pix:
            raise RuntimeError(f"pixRead が NULL を返しました: {image_path}")
        try:
            self.lib.TessBaseAPISetImage2(handle, ctypes.c_void_p(pix))
            ptr = self.lib.TessBaseAPIGetUTF8Text(handle)
            if not ptr:
                raise RuntimeError("TessBaseAPIGetUTF8Text が NULL を返しました")
            try:
                return ctypes.cast(ptr, ctypes.c_char_p).value.decode("utf-8")
            finally:
                self.lib.TessDeleteText(ctypes.c_void_p(ptr))
        finally:
            pix_ref = ctypes.c_void_p(pix)
            self.lept.pixDestroy(ctypes.byref(pix_ref))

    def close(self, handle):
        self.lib.TessBaseAPIEnd(handle)
        self.lib.TessBaseAPIDelete(handle)


def lambda_handler(event, context):
    checks = []
    timings = {}

    # --- 3-0: Layer の展開状況 -------------------------------------------
    def layout():
        def ls(p):
            try:
                return sorted(os.listdir(p))
            except FileNotFoundError:
                return "<not found>"

        return {
            "/opt": ls("/opt"),
            LIB_DIR: ls(LIB_DIR),
            BIN_DIR: ls(BIN_DIR),
            TESSDATA_DIR: ls(TESSDATA_DIR),
            "/opt/python(先頭のみ)": ls("/opt/python")[:8],
            "sample_image_exists": os.path.isfile(IMAGE),
        }

    check(checks, "3-0", "Layer が /opt に展開されている")(layout)

    # --- 3-3: libtesseract.so のロード ------------------------------------
    tess = None

    def load_lib():
        nonlocal tess
        tess = CtypesTesseract()
        return {"lib_path": tess.lib_path}

    load_entry = check(checks, "3-3", "ctypes で libtesseract.so をロードできる")(load_lib)

    # --- 3-4: バージョン取得（早期ゲート） ---------------------------------
    check(checks, "3-4", "TessVersion() でバージョン文字列が取得できる")(
        lambda: {"version": tess.version()} if tess else _fail_no_lib()
    )

    # leptonica のロード（方式① の画像入力に必要）
    check(checks, "3-4b", "leptonica をロードできる")(
        lambda: {"lept_path": tess.load_leptonica()} if tess else _fail_no_lib()
    )

    # --- 3-5: 言語データの解決 --------------------------------------------
    handle = None

    def init_api():
        nonlocal handle
        if tess is None:
            _fail_no_lib()
        handle = tess.create_and_init()
        return {
            "tessdata_dir": TESSDATA_DIR,
            "lang": LANG,
            "init3_returncode": 0,
            "TESSDATA_PREFIX_env": os.environ.get("TESSDATA_PREFIX"),
            "note": (
                "TessBaseAPIInit3 の第2引数でパスを明示指定した。"
                "環境変数 TESSDATA_PREFIX は未設定でも成立する"
            ),
        }

    init_entry = check(checks, "3-5", "TessBaseAPIInit3 が成功する（言語データの解決）")(init_api)

    # --- 3-6: 方式① による OCR 実行（Q6） ----------------------------------
    def ocr_ctypes():
        if tess is None or handle is None:
            raise RuntimeError("初期化に失敗しているため実行できません")
        durations = []
        text = ""
        for _ in range(REPEAT):
            started = time.perf_counter()
            text = tess.ocr(handle, IMAGE)
            durations.append(round((time.perf_counter() - started) * 1000, 3))
        timings["ctypes_ms"] = durations
        if not _matches_expected(text):
            raise AssertionError(
                f"認識結果が期待値と一致しません: {_normalize(text)!r} != {EXPECTED_TEXT!r}"
            )
        return {
            "recognized": _normalize(text),
            "expected": EXPECTED_TEXT,
            "durations_ms": durations,
        }

    check(checks, "3-6", "【方式①】ctypes で OCR が実行できる")(ocr_ctypes)

    if handle is not None and tess is not None:
        tess.close(handle)

    # --- 3-7: 実行ファイルの疎通 -------------------------------------------
    def tool_version():
        proc = subprocess.run(
            [TOOL, "--version"], capture_output=True, text=True, timeout=20, check=False
        )
        if proc.returncode != 0:
            raise RuntimeError(f"終了コード {proc.returncode} / {proc.stderr.strip()!r}")
        return {"stdout": proc.stdout.strip().splitlines()}

    check(checks, "3-7", "subprocess で /opt/bin/tesseract --version が成功する")(tool_version)

    # --- 3-8: Python パッケージの import -----------------------------------
    def import_packages():
        import PIL  # noqa: PLC0415
        import pytesseract  # noqa: PLC0415

        return {
            "pytesseract": getattr(pytesseract, "__version__", "unknown"),
            "Pillow": PIL.__version__,
            "pytesseract_path": os.path.dirname(pytesseract.__file__),
            "PIL_path": os.path.dirname(PIL.__file__),
        }

    import_entry = check(checks, "3-8", "/opt/python から pytesseract と PIL を import できる")(
        import_packages
    )

    # --- 3-9: 方式② による OCR 実行 ----------------------------------------
    def ocr_pytesseract():
        if not import_entry["ok"]:
            raise RuntimeError("パッケージを import できていないため実行できません")
        import pytesseract  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        pytesseract.pytesseract.tesseract_cmd = TOOL

        durations = []
        text = ""
        with Image.open(IMAGE) as img:
            for _ in range(REPEAT):
                started = time.perf_counter()
                # pytesseract は config を空白で分割して引数に渡すため、
                # 引用符を付けるとリテラルとして残ってしまう。パスに空白が
                # 無いことを前提に、引用符なしで指定する。
                text = pytesseract.image_to_string(
                    img, lang=LANG, config=f"--tessdata-dir {TESSDATA_DIR}"
                )
                durations.append(round((time.perf_counter() - started) * 1000, 3))
        timings["pytesseract_ms"] = durations
        if not _matches_expected(text):
            raise AssertionError(
                f"認識結果が期待値と一致しません: {_normalize(text)!r} != {EXPECTED_TEXT!r}"
            )
        return {
            "recognized": _normalize(text),
            "expected": EXPECTED_TEXT,
            "durations_ms": durations,
            "tesseract_cmd": TOOL,
        }

    check(checks, "3-9", "【方式②】pytesseract で OCR が実行できる")(ocr_pytesseract)

    # --- 3-10: 一時ファイルの書き込み先 -------------------------------------
    def temp_location():
        tmpdir = tempfile.gettempdir()
        with tempfile.NamedTemporaryFile(prefix="lleval-", suffix=".txt") as f:
            f.write(b"write test")
            f.flush()
            path = f.name
        return {
            "TMPDIR_env": os.environ.get("TMPDIR"),
            "tempfile.gettempdir()": tmpdir,
            "written_to": path,
            "note": (
                "TMPDIR 未設定でも tempfile は /tmp にフォールバックするため、"
                "pytesseract の一時ファイル書き込みは追加設定なしで成立する"
            ),
        }

    check(checks, "3-10", "一時ファイルが書き込み可能な領域に作られる")(temp_location)

    # --- 3-11: 両方式の性能比較 --------------------------------------------
    def compare():
        c = timings.get("ctypes_ms")
        p = timings.get("pytesseract_ms")
        if not c or not p:
            raise RuntimeError("両方式の計測値が揃っていないため比較できません")
        c_avg = sum(c) / len(c)
        p_avg = sum(p) / len(p)
        return {
            "ctypes_ms": c,
            "pytesseract_ms": p,
            "ctypes_avg_ms": round(c_avg, 3),
            "pytesseract_avg_ms": round(p_avg, 3),
            "overhead_ms": round(p_avg - c_avg, 3),
            "ratio": round(p_avg / c_avg, 2) if c_avg else None,
        }

    check(checks, "3-11", "両方式の実行時間を比較する")(compare)

    # --- 3-1: Layer サイズ（解凍後の実測） ----------------------------------
    def layer_size():
        total = 0
        per_dir = {}
        for entry in sorted(os.listdir("/opt")):
            path = os.path.join("/opt", entry)
            size = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    fp = os.path.join(root, name)
                    if not os.path.islink(fp):
                        size += os.path.getsize(fp)
            per_dir[path] = size
            total += size
        limit = 250 * 1024 * 1024
        return {
            "per_directory_bytes": per_dir,
            "total_bytes": total,
            "total_mb": round(total / 1024 / 1024, 2),
            "limit_mb": 250,
            "within_limit": total < limit,
            "headroom_mb": round((limit - total) / 1024 / 1024, 2),
        }

    check(checks, "3-1", "解凍後サイズが 250MB 以内に収まっている")(layer_size)

    passed = sum(1 for c in checks if c["ok"])
    result = {
        "phase": 3,
        "summary": {
            "passed": passed,
            "total": len(checks),
            "all_passed": passed == len(checks),
            "ocr_ctypes_ok": any(c["item"] == "3-6" and c["ok"] for c in checks),
            "ocr_pytesseract_ok": any(c["item"] == "3-9" and c["ok"] for c in checks),
        },
        "checks": checks,
        "environment": {
            "python": sys.version.split()[0],
            "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _fail_no_lib():
    raise RuntimeError("libtesseract.so をロードできていないため実行できません")
