# 検証結果レポート

対応する要件定義: [requirements.md](requirements.md)

| 項目 | 内容 |
| --- | --- |
| AWS アカウント | `543803375852` |
| リージョン | `ap-northeast-1` |
| ランタイム | `python3.13` / `arm64` |

## 進捗

| フェーズ | 状態 | 実施日 |
| --- | --- | --- |
| Phase 0: 環境準備 | ✅ 完了 | 2026-08-14 |
| Phase 1: 依存なし自作 `.so` | ✅ 完了 | 2026-08-14 |
| Phase 2: 依存あり `.so` / 実行バイナリ | 未着手 | — |
| Phase 3: Tesseract | 未着手 | — |

---

## Phase 0: 環境準備

### 0-1 / 0-2. ビルド環境（Finch）

| 確認項目 | 結果 |
| --- | --- |
| Finch バージョン | v1.17.2 |
| VM 状態 | `Running` |
| ビルドイメージ | `public.ecr.aws/lambda/python:3.13` |
| アーキテクチャ | `aarch64` |
| OS | Amazon Linux 2023 |
| glibc | 2.34 |
| コンパイラ | イメージに **gcc は未同梱**。`dnf install -y gcc` で導入可能 |
| ホスト⇔コンテナのファイル共有 | ボリュームマウント（`-v`）で双方向に成立 |

コンテナ内で生成した共有ライブラリをホスト側の `file` で判定した結果:

```
ELF 64-bit LSB shared object, ARM aarch64, version 1 (SYSV), dynamically linked
```

**→ Phase 0 成功基準①（aarch64 の ELF 生成）を満たす。**

#### 留意点

- `finch vm init` の過程で、コンテナ公開ポートを macOS 側から参照するためのネットワーク設定（`socket_vmnet`）に root 権限が要求されるが、**未設定のまま進行**している。ビルド用途のみでポート公開を行わないため影響はなく、実際にビルドは完走している。

### 0-3. IAM ロール

```
arn:aws:iam::543803375852:role/lleval-lambda-role
```

付与ポリシー: `AWSLambdaBasicExecutionRole` のみ。

### 0-4 / 0-5. スクリプト整備

`scripts/` 配下に整備。いずれも冪等に実行できる。

| スクリプト | 役割 |
| --- | --- |
| `config.sh` | リージョン・命名・ランタイム・ビルド環境の共通変数 |
| `common.sh` | ログ出力、命名規則、コンテナ実行などの共通関数 |
| `setup-role.sh` | IAM 実行ロールの作成 |
| `build-layer.sh` | コンテナ内で Layer をビルドし ZIP 化。**aarch64 ELF であることを自動検証** |
| `deploy.sh` | Layer 発行 + 関数の作成／更新 |
| `invoke.sh` | invoke してレスポンスと実行ログを表示 |
| `cleanup.sh` | 作成リソースの削除（`--all` で IAM ロールとログも） |

### 0-6. Lambda 疎通確認と実行環境プローブ

Layer を付けない状態の関数 `lleval-phase0-fn` をデプロイ・invoke し、正常応答を確認。
**→ Phase 0 成功基準②を満たす。**

あわせて、要件定義 §3.6 に「既知仕様」として記載していた前提を実測で確認した。

#### ランタイム

| 項目 | 実測値 |
| --- | --- |
| `platform.machine()` | `aarch64` |
| Python | 3.13.14 |
| カーネル | `5.10.255-260-301.1061.amzn2.aarch64` |
| libc | **glibc 2.34** |

> ビルド環境（Finch / AL2023 / glibc 2.34）と**完全に一致**している。R2（glibc 不一致）のリスクは実質的に解消。

#### パス関連 — §3.6 の前提はすべて成立

| 確認項目 | 結果 | 実測値 |
| --- | --- | --- |
| `LD_LIBRARY_PATH` に `/opt/lib` | ✅ 含まれる | `/var/lang/lib:/lib64:/usr/lib64:/var/runtime:/var/runtime/lib:/var/task:/var/task/lib:/opt/lib` |
| `PATH` に `/opt/bin` | ✅ 含まれる | `/var/lang/bin:/usr/local/bin:/usr/bin/:/bin:/opt/bin` |
| `sys.path` に `/opt/python` 系 | ✅ 含まれる | `/opt/python/lib/python3.13/site-packages`, `/opt/python` |

**→ Phase 1 の 1-4（ライブラリ名のみでのロード）、Phase 2 の 2-4（`/opt/bin` からの実行）、Phase 3 の 3-8（`/opt/python` からの import）は、いずれも環境側の前提が整っていることを確認した。**

なお `LD_LIBRARY_PATH` において `/opt/lib` は**最後尾**にある。同名ライブラリがシステム側（`/lib64`, `/usr/lib64`）に存在する場合はそちらが優先されるため、Phase 3 で Tesseract の依存ライブラリを配置する際は注意が必要。

#### ファイルシステム

| パス | 書き込み可否 | 備考 |
| --- | --- | --- |
| `/tmp` | ✅ 可 | 一時ファイルの出力先 |
| `/opt` | ❌ 不可 | Layer の展開先。読み取り専用 |
| `/var/task` | ❌ 不可 | 関数コードの展開先。読み取り専用 |

Layer 未アタッチ時、`/opt` は**存在するが空**であり、`/opt/lib` は存在しない。

#### 環境変数

| 変数 | 値 |
| --- | --- |
| `AWS_EXECUTION_ENV` | `AWS_Lambda_python3.13` |
| `TMPDIR` | **未設定** |
| `TESSDATA_PREFIX` | 未設定（Phase 3 で設定を検討） |

> `TMPDIR` は未設定だが、Python の `tempfile` は `TMPDIR` / `TEMP` / `TMP` の順に参照し、いずれも無ければ `/tmp` にフォールバックする。したがって Phase 3 の方式②（`pytesseract` が入力画像を一時ファイルへ書き出す）は、追加設定なしで `/tmp` を使う想定。3-10 で実測して確認する。

#### ベースライン計測値（Layer なし）

| 指標 | 実測値 |
| --- | --- |
| Init Duration（コールドスタート） | **81.93 ms** |
| Duration | 21.94 ms |
| Max Memory Used | **39 MB** |
| Memory Size | 512 MB |

> 以降のフェーズでは、この値との差分が Layer の追加コストとなる。

### Phase 0 まとめ

| 成功基準 | 判定 |
| --- | --- |
| ビルド環境で aarch64 の ELF 共有ライブラリを生成できる | ✅ |
| Layer なしの関数を CLI のみでデプロイ・invoke でき正常応答を得る | ✅ |

**Phase 0 完了。Phase 1 へ進行可能。**

---

## Phase 1: 依存なしの自作共有ライブラリ

**本検証の核心（Q1・Q2）に対する回答が得られたフェーズ。**

### 検証対象

外部依存を持たない C 製の共有ライブラリ `libeval.so` を Layer の `lib/` に配置し、`ctypes` から呼び出す。

| 関数 | シグネチャ |
| --- | --- |
| 整数演算 | `int add(int a, int b)` |
| 文字列返却 | `const char *version(void)` |

### ビルド結果

`public.ecr.aws/lambda/python:3.13` (linux/arm64) コンテナ内で `gcc -shared -fPIC -O2` によりビルド。

```
staging/lib/libeval.so: ELF 64-bit LSB shared object, ARM aarch64, version 1 (SYSV), dynamically linked
```

公開シンボル:

```
0000000000010160 T add
0000000000010168 T version
```

依存ライブラリ（`ldd`）— システム提供の libc のみで、同梱が必要な依存はない:

```
linux-vdso.so.1
libc.so.6 => /lib64/libc.so.6
/lib/ld-linux-aarch64.so.1
```

| 指標 | 実測値 |
| --- | --- |
| Layer ZIP サイズ | 2,932 bytes |
| Layer 解凍後サイズ | 201,080 bytes |

> `.so` 本体が 201 KB あるのは、`-O2` かつ未 strip でデバッグ情報・シンボルを含むため。Phase 3 でサイズが問題になった場合、`strip` の効果を見積もる材料になる。

### 検証項目の結果 — **6/6 すべて成功**

| # | 検証項目 | 判定 | 実測 |
| --- | --- | --- | --- |
| 1-2 | Layer が `/opt` に展開されている | ✅ | `/opt` = `["lib"]`、`/opt/lib` = `["libeval.so"]`（201,080 bytes） |
| 1-3 | **絶対パス指定でのロード** | ✅ | `ctypes.CDLL("/opt/lib/libeval.so")` 成功（0.643 ms） |
| 1-4 | **ライブラリ名のみでのロード（Q2）** | ✅ | `ctypes.CDLL("libeval.so")` 成功（0.117 ms） |
| 1-5 | `add(2, 3)` | ✅ | `5`（期待値どおり） |
| 1-6 | `version()` のデコード | ✅ | `"libeval 1.0.0 (phase1)"`（期待値どおり） |
| 補足 | `restype` 未宣言時の挙動 | ✅ 観測 | 下記参照 |

**Q1・Q2 への回答**

> **Q1: Layer に置いた `.so` を Python の `ctypes` でロードして関数呼び出しできるか → できる。**
>
> **Q2: `LD_LIBRARY_PATH` の追加設定なしに `/opt/lib` の `.so` が解決されるか → される。**

1-4 が成功したことで、`/opt/lib` が `LD_LIBRARY_PATH` に含まれている効果が実際に働いていることを確認した。**環境変数の追加設定も絶対パス指定も不要**である。

なお 1-3 と 1-4 で得られたハンドル値は同一（`27bb3480`）であり、動的リンカが同じライブラリを再利用していることも確認できた。

### 補足: `restype` 未宣言時の挙動（Phase 3 への申し送り）

`version()` を `restype` 未宣言のまま呼び出した実測結果:

| 項目 | 値 |
| --- | --- |
| 返り値の型 | `int` |
| 返り値 | `-2134384640` |

`ctypes` は `restype` 未宣言の場合、戻り値を既定の `int`（32bit）として扱う。そのため 64bit ポインタが切り詰められ、文字列として解釈できない。

**Phase 3 で `libtesseract.so` の C API（`TessVersion()` や `TessBaseAPIGetUTF8Text()` などポインタを返す関数）を呼ぶ際は `restype` の宣言が必須。** 例外は送出されず不正な値が返るだけなので、宣言漏れは発見しにくい。

### 計測値

| 指標 | Phase 0（Layer なし） | Phase 1（Layer あり） |
| --- | --- | --- |
| Init Duration（コールドスタート） | 81.93 ms | **71.38 ms** |
| Duration（コールド時） | 21.94 ms | 3.33 ms |
| Duration（ウォーム、3 回） | — | 2.06 / 1.88 / 2.09 ms |
| Max Memory Used | 39 MB | **37 MB** |

> Phase 1 の Init Duration が Phase 0 を下回っているが、これは**測定のばらつきの範囲**であり、Layer によって速くなったわけではない。読み取るべきは「**200 KB 程度の Layer ではコールドスタートに有意な影響が出ない**」という点。ライブラリのロード自体も 0.643 ms と軽微である。Phase 3 では Layer が桁違いに大きくなるため、ここが比較の基準になる。

### Phase 1 まとめ

| 受入条件 | 判定 |
| --- | --- |
| 1-3（絶対パスでのロード）と 1-5（関数呼び出し）が成功する | ✅ |

**Phase 1 完了。本検証の最低到達点をクリアした。Phase 2 へ進行可能。**

---

## 発生した問題と対処

| # | フェーズ | 事象 | 原因 | 対処 |
| --- | --- | --- | --- | --- |
| 1 | 0 | `finch vm init` でネットワーク依存関係のインストールに失敗 | `socket_vmnet` の配置に root 権限が必要 | ビルド用途では不要のためスキップ。VM 自体は正常起動しビルドも成立 |
| 2 | 0 | `invoke.sh` が `InvalidRequestContentException` で失敗 | デフォルトペイロードのシェル展開が `{\}` となり不正な JSON になっていた | デフォルト値の組み立てを修正 |
