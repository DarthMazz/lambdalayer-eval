"""Phase 2: 依存関係を持つ共有ライブラリと実行ファイルの検証.

Tesseract は libtesseract.so が leptonica 等に依存し、tesseract CLI が
libtesseract.so にリンクするという構造を持つ。Phase 2 では同じ構造を
自作ライブラリで再現し、Phase 3 で発生しうる依存解決の失敗を先に潰す。

要件定義の検証項目 2-1 〜 2-5 に対応する。
"""

import ctypes
import json
import os
import stat
import subprocess
import time

LIB_DIR = "/opt/lib"
BIN_DIR = "/opt/bin"
MAIN_LIB = os.path.join(LIB_DIR, "libevalmain.so")
DEP_LIB = os.path.join(LIB_DIR, "libevaldep.so")
BROKEN_LIB = "/opt/broken/libbroken.so"
TOOL = os.path.join(BIN_DIR, "evaltool")

EXPECTED_COMPUTE = (6, 7, 43)  # dep_multiply(6, 7) + 1
EXPECTED_MAIN_VERSION = "libevalmain 1.0.0 (phase2)"
EXPECTED_DEP_VERSION = "libevaldep 1.0.0 (phase2)"


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


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return "<not found>"


def _bind_main(lib):
    lib.compute.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.compute.restype = ctypes.c_int
    lib.main_version.argtypes = []
    lib.main_version.restype = ctypes.c_char_p
    lib.dep_version_via_main.argtypes = []
    lib.dep_version_via_main.restype = ctypes.c_char_p
    return lib


def lambda_handler(event, context):
    checks = []

    # --- 2-0: Layer の展開状況 -------------------------------------------
    check(checks, "2-0", "Layer が /opt に展開されている")(
        lambda: {
            "/opt": _listdir("/opt"),
            LIB_DIR: _listdir(LIB_DIR),
            BIN_DIR: _listdir(BIN_DIR),
            "/opt/broken": _listdir("/opt/broken"),
            "libmissing.so_同梱されていないこと": "libmissing.so" not in _listdir(LIB_DIR),
        }
    )

    # --- 2-1: 依存 .so の自動解決（Q3） ------------------------------------
    # libevalmain.so をロードするだけで、依存先の libevaldep.so まで
    # 解決されるかを確認する。
    main_entry = check(checks, "2-1", "依存を持つ .so が依存先ごとロードできる（Q3）")(
        lambda: {"loaded": str(ctypes.CDLL(MAIN_LIB))}
    )

    lib = _bind_main(ctypes.CDLL(MAIN_LIB)) if main_entry["ok"] else None

    # ロード成功だけでは依存が本当に解決されたとは言えないため、
    # 依存先の関数を実際に呼んで結果を確認する。
    def call_through_dependency():
        if lib is None:
            raise RuntimeError("libevalmain.so をロードできていません")
        a, b, expected = EXPECTED_COMPUTE
        actual = lib.compute(a, b)
        if actual != expected:
            raise AssertionError(f"compute({a}, {b}) = {actual} (期待値 {expected})")
        main_ver = lib.main_version().decode("utf-8")
        dep_ver = lib.dep_version_via_main().decode("utf-8")
        if main_ver != EXPECTED_MAIN_VERSION or dep_ver != EXPECTED_DEP_VERSION:
            raise AssertionError(f"バージョン不一致: main={main_ver!r} dep={dep_ver!r}")
        return {
            "call": f"compute({a}, {b})",
            "actual": actual,
            "expected": expected,
            "main_version": main_ver,
            "dep_version_via_main": dep_ver,
            "note": "依存先 libevaldep.so の関数が実際に実行されている",
        }

    check(checks, "2-1b", "依存先の関数呼び出しが実際に成立する")(call_through_dependency)

    # --- 2-2: 依存関係の可視化 ---------------------------------------------
    def loaded_maps():
        with open("/proc/self/maps", encoding="utf-8") as f:
            lines = f.read().splitlines()
        opt_libs = sorted(
            {line.split()[-1] for line in lines if "/opt/" in line}
        )
        return {
            "opt_mapped_files": opt_libs,
            "dep_is_mapped": any(p.endswith("libevaldep.so") for p in opt_libs),
            "main_is_mapped": any(p.endswith("libevalmain.so") for p in opt_libs),
        }

    check(checks, "2-2", "/proc/self/maps に /opt/lib のライブラリがマップされている")(
        loaded_maps
    )

    # --- 2-3: 依存解決に失敗する場合のエラー記録 ---------------------------
    # 失敗すること自体が期待結果。エラーメッセージを記録する。
    def broken_load():
        try:
            ctypes.CDLL(BROKEN_LIB)
        except OSError as e:
            return {
                "loaded": False,
                "expected_failure": True,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "note": "依存の洗い出しに漏れがあるとこのエラーになる",
            }
        raise AssertionError(
            "libbroken.so のロードが成功してしまった（失敗するはずの検証）"
        )

    check(checks, "2-3", "依存 .so が欠けている場合のエラーを記録する")(broken_load)

    # --- 2-4: /opt/bin の実行ファイル起動（Q4） -----------------------------
    def run_tool(command, label):
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"終了コード {proc.returncode} / stderr={proc.stderr.strip()!r}"
            )
        return {
            "invocation": label,
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip().splitlines(),
        }

    check(checks, "2-4", "絶対パス指定で /opt/bin の実行ファイルを起動できる")(
        lambda: run_tool([TOOL, "6", "7"], "絶対パス")
    )

    # コマンド名のみでの起動は PATH に /opt/bin が含まれることの実証になる。
    # 同時に、実行ファイルが LD_LIBRARY_PATH 経由で /opt/lib の
    # libevaldep.so を解決できていることも示す（tesseract CLI と同じ構造）。
    check(checks, "2-4b", "コマンド名のみで実行できる（PATH と実行時リンクの実証）")(
        lambda: run_tool(["evaltool", "3", "4"], "コマンド名のみ")
    )

    # --- 2-5: パーミッションの保持 -----------------------------------------
    def permissions():
        entries = {}
        for path in (TOOL, MAIN_LIB, DEP_LIB):
            mode = os.stat(path).st_mode
            entries[path] = {
                "mode": oct(stat.S_IMODE(mode)),
                "executable": os.access(path, os.X_OK),
            }
        if not entries[TOOL]["executable"]:
            raise AssertionError(f"{TOOL} に実行権限がありません")
        return entries

    check(checks, "2-5", "ZIP 化を経ても実行権限が保持されている")(permissions)

    passed = sum(1 for c in checks if c["ok"])
    result = {
        "phase": 2,
        "summary": {
            "passed": passed,
            "total": len(checks),
            "all_passed": passed == len(checks),
        },
        "checks": checks,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
