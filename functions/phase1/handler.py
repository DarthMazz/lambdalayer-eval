"""Phase 1: Layer に配置した依存なしネイティブライブラリを ctypes で呼び出す.

本検証の核心（Q1・Q2）を最小構成で確かめる。
要件定義の検証項目 1-2 〜 1-7 に対応する。

各チェックは失敗しても例外を送出せず結果に記録するため、1 回の invoke で
すべての項目の成否を一度に把握できる。
"""

import ctypes
import json
import os
import platform
import sys
import time

LIB_DIR = "/opt/lib"
LIB_NAME = "libeval.so"
LIB_PATH = os.path.join(LIB_DIR, LIB_NAME)

EXPECTED_ADD = (2, 3, 5)
EXPECTED_VERSION = "libeval 1.0.0 (phase1)"


def check(checks, item, description):
    """チェックを実行し、結果を checks に記録するデコレータ的ヘルパ。"""

    def runner(fn):
        entry = {"item": item, "description": description}
        started = time.perf_counter()
        try:
            entry["result"] = fn()
            entry["ok"] = True
        except Exception as e:  # noqa: BLE001 - 全項目を走査したいので握る
            entry["ok"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        checks.append(entry)
        return entry

    return runner


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return "<not found>"


def _bind(lib):
    """argtypes / restype を明示的に宣言する。

    特に version() は restype を宣言しないと戻り値が既定の int (32bit) と
    みなされ、64bit ポインタが切り詰められる。
    """
    lib.add.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.add.restype = ctypes.c_int
    lib.version.argtypes = []
    lib.version.restype = ctypes.c_char_p
    return lib


def lambda_handler(event, context):
    checks = []

    # --- 1-2: Layer が /opt に展開されているか ---------------------------
    check(checks, "1-2", "Layer が /opt に展開されている")(
        lambda: {
            "/opt": _listdir("/opt"),
            LIB_DIR: _listdir(LIB_DIR),
            "lib_exists": os.path.isfile(LIB_PATH),
            "size_bytes": os.path.getsize(LIB_PATH) if os.path.isfile(LIB_PATH) else None,
        }
    )

    # --- 1-3: 絶対パス指定でのロード ------------------------------------
    abs_entry = check(checks, "1-3", "絶対パス指定で CDLL がロードできる")(
        lambda: {"loaded": str(ctypes.CDLL(LIB_PATH))}
    )

    # --- 1-4: ライブラリ名のみでのロード（Q2） ---------------------------
    # 成功すれば LD_LIBRARY_PATH に /opt/lib が含まれることの実証になる。
    check(checks, "1-4", "ライブラリ名のみで CDLL がロードできる（LD_LIBRARY_PATH の実証）")(
        lambda: {"loaded": str(ctypes.CDLL(LIB_NAME))}
    )

    # 以降の関数呼び出しは絶対パスでロードしたものを使う
    lib = _bind(ctypes.CDLL(LIB_PATH)) if abs_entry["ok"] else None

    # --- 1-5: 整数演算の呼び出し ----------------------------------------
    a, b, expected = EXPECTED_ADD

    def call_add():
        if lib is None:
            raise RuntimeError("ライブラリをロードできていないため実行できません")
        actual = lib.add(a, b)
        if actual != expected:
            raise AssertionError(f"add({a}, {b}) = {actual} (期待値 {expected})")
        return {"call": f"add({a}, {b})", "actual": actual, "expected": expected}

    check(checks, "1-5", "add() が期待どおりの値を返す")(call_add)

    # --- 1-6: 文字列（ポインタ）返却 -------------------------------------
    def call_version():
        if lib is None:
            raise RuntimeError("ライブラリをロードできていないため実行できません")
        raw = lib.version()
        actual = raw.decode("utf-8")
        if actual != EXPECTED_VERSION:
            raise AssertionError(f"version() = {actual!r} (期待値 {EXPECTED_VERSION!r})")
        return {"actual": actual, "expected": EXPECTED_VERSION}

    check(checks, "1-6", "version() の戻り値をデコードできる")(call_version)

    # --- 補足: restype を宣言しない場合の挙動 -----------------------------
    # Phase 3 で libtesseract の C API を呼ぶ際の注意点を実測で残す。
    def restype_omitted():
        if lib is None:
            raise RuntimeError("ライブラリをロードできていないため実行できません")
        bare = ctypes.CDLL(LIB_PATH)  # argtypes/restype を宣言しない
        value = bare.version()
        return {
            "returned_type": type(value).__name__,
            "returned_value": value,
            "note": (
                "restype 未宣言だと戻り値が int(32bit) 扱いになり、"
                "64bit ポインタが切り詰められて文字列として解釈できない"
            ),
        }

    check(checks, "補足", "restype を宣言しない場合の挙動を観測する")(restype_omitted)

    # --- 1-7: 実行環境情報 ------------------------------------------------
    environment = {
        "machine": platform.machine(),
        "python_version": sys.version.split()[0],
        "libc": "-".join(platform.libc_ver()),
        "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
        "PATH": os.environ.get("PATH", ""),
    }

    passed = sum(1 for c in checks if c["ok"])
    result = {
        "phase": 1,
        "summary": {
            "passed": passed,
            "total": len(checks),
            "all_passed": passed == len(checks),
        },
        "checks": checks,
        "environment": environment,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
