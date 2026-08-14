"""Phase 0: 実行環境プローブ.

Layer を付けない状態の Lambda 実行環境を観測し、以降のフェーズの前提
（要件定義 §3.6）を実測で確認するための関数。

確認すること:
  - アーキテクチャと Python バージョンが想定どおりか
  - LD_LIBRARY_PATH に /opt/lib が含まれるか   … Phase 1 の 1-4 の前提
  - PATH に /opt/bin が含まれるか               … Phase 2 の 2-4 の前提
  - sys.path に /opt/python 系が含まれるか      … Phase 3 の 3-8 の前提
  - Layer 未アタッチ時に /opt がどう見えるか
"""

import json
import os
import platform
import sys


def _probe_path(env_name, expected):
    """環境変数を : で分割し、期待するパスが含まれるかを判定する。"""
    raw = os.environ.get(env_name, "")
    entries = [e for e in raw.split(":") if e]
    return {
        "raw": raw,
        "entries": entries,
        "expected": expected,
        "contains_expected": expected in entries,
    }


def _listdir(path):
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return "<not found>"
    except PermissionError:
        return "<permission denied>"


def lambda_handler(event, context):
    result = {
        "phase": 0,
        "runtime": {
            "machine": platform.machine(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "libc": "-".join(platform.libc_ver()),
        },
        "library_path": _probe_path("LD_LIBRARY_PATH", "/opt/lib"),
        "exec_path": _probe_path("PATH", "/opt/bin"),
        "sys_path": {
            "entries": sys.path,
            "opt_entries": [p for p in sys.path if p.startswith("/opt")],
        },
        "opt": {
            "exists": os.path.isdir("/opt"),
            "contents": _listdir("/opt"),
            "lib_contents": _listdir("/opt/lib"),
        },
        "writable": {
            "/tmp": os.access("/tmp", os.W_OK),
            "/opt": os.access("/opt", os.W_OK),
            "/var/task": os.access("/var/task", os.W_OK),
        },
        "env_selected": {
            k: os.environ.get(k)
            for k in (
                "AWS_LAMBDA_FUNCTION_NAME",
                "AWS_LAMBDA_FUNCTION_MEMORY_SIZE",
                "AWS_EXECUTION_ENV",
                "TMPDIR",
                "TESSDATA_PREFIX",
            )
        },
    }

    # 実行ログにも出して CloudWatch から追えるようにする
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
