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
| Phase 2: 依存あり `.so` / 実行バイナリ | ✅ 完了 | 2026-08-14 |
| Phase 3: Tesseract | ✅ 完了 | 2026-08-14 |

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

## Phase 2: 依存関係を持つライブラリと実行バイナリ

**Phase 3 で最も詰まりやすい「依存解決」を、Tesseract と同じ構造を自作ライブラリで再現して先に検証したフェーズ。**

### 検証対象の構造

Tesseract の実構造を意図的に模している。

| Phase 2 の構成要素 | 対応する Phase 3（Tesseract）の要素 |
| --- | --- |
| `/opt/lib/libevalmain.so`（`libevaldep.so` に依存） | `libtesseract.so`（leptonica 等に依存） |
| `/opt/lib/libevaldep.so`（依存される側） | `libleptonica.so` |
| `/opt/bin/evaltool`（`libevaldep.so` にリンクする実行ファイル） | `tesseract` CLI（`libtesseract.so` にリンク） |
| `/opt/broken/libbroken.so`（実体のない依存を持つ） | 依存の洗い出しに漏れがあった場合の再現 |

**rpath は一切埋め込んでいない。** 実行時に `LD_LIBRARY_PATH`（`/opt/lib` を含む）で解決されるかどうかが検証対象であるため。

### ビルド結果

`readelf -d` で記録された依存（DT_NEEDED）:

| 生成物 | DT_NEEDED |
| --- | --- |
| `lib/libevalmain.so` | `libevaldep.so`, `libc.so.6` |
| `bin/evaltool` | `libevaldep.so`, `libc.so.6` |
| `broken/libbroken.so` | `libmissing.so`, `libc.so.6` |

`libbroken.so` に対する `ldd` は意図どおり `libmissing.so => not found` となり、依存が欠けた状態を作れている。

| 指標 | 実測値 |
| --- | --- |
| Layer ZIP サイズ | 12,675 bytes |
| Layer 解凍後サイズ | 805,888 bytes |

### 検証項目の結果 — **8/8 すべて成功**

| # | 検証項目 | 判定 | 実測 |
| --- | --- | --- | --- |
| 2-0 | Layer が `/opt` に展開されている | ✅ | `/opt` = `["bin", "broken", "lib"]`。`libmissing.so` は同梱されていない |
| 2-1 | **依存 `.so` の自動解決（Q3）** | ✅ | `ctypes.CDLL("/opt/lib/libevalmain.so")` 成功（1.432 ms） |
| 2-1b | **依存先の関数呼び出しが実際に成立** | ✅ | `compute(6, 7)` = `43`。`dep_version_via_main()` が `"libevaldep 1.0.0 (phase2)"` を返す |
| 2-2 | 依存関係の可視化 | ✅ | `/proc/self/maps` に `libevaldep.so` と `libevalmain.so` の両方がマップされている |
| 2-3 | 依存解決失敗時のエラー記録 | ✅ 期待どおり失敗 | 下記参照 |
| 2-4 | **`/opt/bin` の実行ファイル起動（Q4）** | ✅ | 絶対パス指定で終了コード 0（2.176 ms） |
| 2-4b | コマンド名のみでの起動 | ✅ | `["evaltool", "3", "4"]` で成功（6.19 ms） |
| 2-5 | パーミッションの保持 | ✅ | `/opt/bin/evaltool` = `0o755`、実行可能 |

**Q3・Q4 への回答**

> **Q3: `.so` が別の `.so` に依存する場合、依存解決は成立するか → 成立する。**
>
> **Q4: 実行バイナリを `/opt/bin` に置いた場合 `subprocess` から起動できるか → できる。**

### 依存解決が「本当に」成立していることの根拠

ロードが成功しただけでは依存先が実際に使われているとは言い切れないため、依存先の関数を経由した呼び出しで確認した。

| 確認 | 結果 |
| --- | --- |
| `compute(6, 7)` | `43`（`= dep_multiply(6,7) + 1`。依存先の関数が実行されている） |
| `dep_version_via_main()` | `"libevaldep 1.0.0 (phase2)"`（依存先の文字列が返っている） |
| `/proc/self/maps` | `/opt/lib/libevaldep.so` が実際にマップされている |

**実行ファイル側でも同様に確認できた。** `evaltool` の標準出力:

```
evaltool 1.0.0 (phase2)
linked_lib=libevaldep 1.0.0 (phase2)
dep_multiply(6,7)=42
```

`linked_lib=` の行は、実行ファイルが `LD_LIBRARY_PATH` 経由で `/opt/lib/libevaldep.so` を解決し、その関数を呼び出せていることを示している。**これは `tesseract` CLI が `libtesseract.so` を解決する経路とまったく同じ構造**であり、Phase 3 の方式②（`pytesseract`）が成立する見込みが高いことを意味する。

### 2-3: 依存が欠けている場合のエラー（Phase 3 への申し送り）

`libbroken.so`（`libmissing.so` に依存するが同梱していない）のロードを試みた実測結果:

| 項目 | 値 |
| --- | --- |
| 例外の型 | `OSError` |
| メッセージ | `libmissing.so: cannot open shared object file: No such file or directory` |

**このメッセージが出た場合、原因は「欠けているライブラリ名がそのまま示されている」ため特定しやすい。** Phase 3 で Tesseract の依存を洗い出す際は、このエラーに出たライブラリ名を Layer に追加していく形で反復すればよい。

### 計測値

| 指標 | Phase 0（Layer なし） | Phase 1（200 KB） | Phase 2（806 KB） |
| --- | --- | --- | --- |
| Init Duration | 81.93 ms | 71.38 ms | 93.94 ms |
| Duration（コールド時） | 21.94 ms | 3.33 ms | 13.95 ms |
| Duration（ウォーム、3 回） | — | 2.06 / 1.88 / 2.09 ms | 5.18 / 5.09 / 4.93 ms |
| Max Memory Used | 39 MB | 37 MB | 39 MB |

> Phase 2 の Duration が Phase 1 より大きいのは、**検証項目としてプロセス起動（`subprocess`）を 2 回行っているため**であり、Layer のサイズによるものではない。実際、`subprocess` 1 回あたり 2.2〜6.2 ms を要しており、これは `ctypes` の関数呼び出し（0.08 ms 以下）と比べて 2 桁大きい。
>
> **Phase 3 の方式比較（3-11）における重要な予測材料になる。** OCR 1 回あたりでこの差が乗るため、呼び出し頻度が高い用途では `ctypes` 方式が有利になる可能性が高い。ただし OCR 本体の処理時間は数百 ms 規模と想定され、相対的な影響度は Phase 3 の実測で判断する。
>
> Init Duration は 71〜94 ms の範囲でばらついており、800 KB 程度の Layer では**サイズによる有意な差は観測できない**。

### Phase 2 まとめ

| 受入条件 | 判定 |
| --- | --- |
| 2-1（依存 `.so` の自動解決）が成功する | ✅ |
| 2-3 は「失敗パターンの記録」であり、失敗すること自体が成果 | ✅ 期待どおり失敗し、エラーメッセージを記録 |

**Phase 2 完了。Phase 3 で必要となる依存解決・実行ファイル起動・パーミッション保持のすべてが成立することを確認した。Phase 3 へ進行可能。**

---

## Phase 3: Tesseract（本番想定）

**Lambda 上で実際に OCR が動作した。方式①（ctypes）・方式②（pytesseract）の双方が成立。**

### 前提調査: Tesseract の入手方法

Amazon Linux 2023 のリポジトリ（利用可能パッケージ 14,339 件）を確認した結果:

| 対象 | 提供状況 |
| --- | --- |
| `tesseract` | **なし** |
| `leptonica` | **なし** |
| ビルド依存一式 | **すべてあり** |

`dnf` での導入（要件定義 §9-2 案 A）は**不成立**。公式アップストリームからのソースビルド（案 B）を採用した。

| 項目 | 採用値 |
| --- | --- |
| Leptonica | 1.87.0 |
| Tesseract | 5.5.3 |
| ビルド方式 | autotools（`configure` / `autogen.sh`） |
| 言語データ | `tessdata_fast` の `eng.traineddata` |

### ビルド結果

同梱したライブラリ（13 個）。`ldd` による再帰的な洗い出しが収束するまで繰り返して確定させた。

```
libtesseract.so.5.0.5   libleptonica.so.6.0.0   libpng16.so.16
libjpeg.so.62           libtiff.so.5            libwebp.so.7
libwebpmux.so.3         libz.so.1               libzstd.so.1
libjbig.so.2.1          libstdc++.so.6          libgcc_s.so.1
libgomp.so.1
```

glibc 本体が提供するもの（`libc` / `libm` / `ld-linux`）は同梱していない。ビルド環境での確認では **未解決の依存はゼロ**。

**`libstdc++` / `libgcc_s` / `libgomp` の同梱は必須だった。** Tesseract は C++ 実装かつ OpenMP を使うため、これらが欠けると Lambda 上でロードに失敗する。

### 検証項目の結果 — **12/12 すべて成功**

| # | 検証項目 | 判定 | 実測 |
| --- | --- | --- | --- |
| 3-0 | Layer が `/opt` に展開されている | ✅ | `bin` / `lib` / `tessdata` / `python` を確認 |
| 3-1 | **解凍後サイズが 250 MB 以内** | ✅ | **38.73 MB**（余裕 211.27 MB） |
| 3-2 | アップロード方式 | ✅ | ZIP 12.7 MB。50 MB 未満のため **S3 経由は不要**、直接アップロードで発行できた |
| 3-3 | `libtesseract.so` のロード | ✅ | `/opt/lib/libtesseract.so`（121.2 ms） |
| 3-4 | `TessVersion()` | ✅ | `"5.5.3"` |
| 3-4b | leptonica のロード | ✅ | `/opt/lib/libleptonica.so` |
| 3-5 | `TessBaseAPIInit3` | ✅ | 戻り値 `0`（561.3 ms） |
| 3-6 | **【方式①】ctypes で OCR** | ✅ | `"HELLO LAMBDA"` |
| 3-7 | 実行ファイルの疎通 | ✅ | `tesseract 5.5.3` / `leptonica-1.87.0` |
| 3-8 | `/opt/python` からの import | ✅ | pytesseract 0.3.13 / Pillow 12.3.0 |
| 3-9 | **【方式②】pytesseract で OCR** | ✅ | `"HELLO LAMBDA"` |
| 3-10 | 一時ファイルの書き込み | ✅ | `/tmp/lleval-xxxx.txt` |
| 3-11 | 両方式の性能比較 | ✅ | 下記 |

**Q5・Q6 への回答**

> **Q5: Tesseract 一式を Layer に収められるか → 収められる。解凍後 38.73 MB で 250 MB 制限に対し 211 MB の余裕がある。**
>
> **Q6: Lambda 上で実際に OCR 結果が得られるか → 得られる。両方式とも期待どおりのテキストを返した。**

### サイズの内訳

| 構成 | サイズ | 割合 |
| --- | --- | --- |
| `/opt/python`（pytesseract + Pillow） | 23.43 MB | 57.7% |
| `/opt/lib`（Tesseract + 依存 13 個） | 12.87 MB | 31.7% |
| `/opt/tessdata`（`eng`） | 4.11 MB | 10.1% |
| `/opt/bin`（`tesseract`） | 0.20 MB | 0.5% |
| **合計** | **38.73 MB** | |

`strip --strip-unneeded` を適用済み。上表は適用後の値。

> **サイズの過半を占めるのは Tesseract 本体ではなく Pillow である。** 方式①（ctypes）だけを採用すれば `/opt/python` の 23.43 MB がまるごと不要になり、**15.3 MB 程度まで縮む**。

### 3-5: 言語データのパス指定

| 項目 | 実測 |
| --- | --- |
| `TESSDATA_PREFIX` 環境変数 | **未設定** |
| 指定方法 | `TessBaseAPIInit3` の第 2 引数に `/opt/tessdata` を直接指定 |
| 結果 | 戻り値 `0`（成功） |

要件定義で懸念していた「`TESSDATA_PREFIX` の指す階層がバージョンによって異なる」問題は、**引数で直接指定することで回避できる**。方式②では `--tessdata-dir` オプションで同様に指定した。環境変数への依存は不要。

> 実装上の注意: `pytesseract` は `config` 文字列を空白で分割してそのまま引数に渡すため、`--tessdata-dir "/opt/tessdata"` のように引用符を付けると**引用符がリテラルとして残り失敗する**。引用符なしで指定すること。

### 3-11: 両方式の性能比較（重要）

| 方式 | 1 回目 | 2 回目 | 3 回目 | 平均 |
| --- | --- | --- | --- | --- |
| **① ctypes** | 182.7 ms | 179.9 ms | 180.1 ms | **180.9 ms** |
| **② pytesseract** | 660.6 ms | 579.0 ms | 599.9 ms | **613.2 ms** |
| 差 | | | | **+432.3 ms（3.39 倍）** |

**この差の主因はプロセス起動コストではない。**

Phase 2 で実測した `subprocess` の起動コストは 1 回あたり 2.2〜6.2 ms であり、432 ms の差を説明できない。実際の要因は **Tesseract の初期化コスト**である。

| 根拠 | 値 |
| --- | --- |
| `TessBaseAPIInit3`（言語データの読み込み含む）の所要時間 | 561.3 ms |
| 方式① の 1 回あたり | 180.9 ms（**初期化済みハンドルを再利用**） |
| 方式② の 1 回あたり | 613.2 ms（**毎回初期化が発生**） |
| 差分 | 432.3 ms ≒ 初期化コスト |

方式② は `tesseract` を毎回プロセスとして起動するため、**呼び出しのたびに言語データの読み込みからやり直す**。方式① は `TessBaseAPICreate` / `TessBaseAPIInit3` で作ったハンドルを保持して使い回せるため、2 回目以降はこのコストが発生しない。

**Lambda のウォームスタートではハンドルをハンドラ外に保持して再利用できるため、この差は実運用でそのまま効く。**

### 計測値

| 指標 | Phase 0（Layer なし） | Phase 1（200 KB） | Phase 2（806 KB） | Phase 3（38.7 MB） |
| --- | --- | --- | --- | --- |
| Init Duration | 81.93 ms | 71.38 ms | 93.94 ms | **91.99 ms** |
| Duration（コールド時） | 21.94 ms | 3.33 ms | 13.95 ms | 3753.56 ms |
| Duration（ウォーム） | — | 約 2 ms | 約 5 ms | 2661〜2749 ms |
| Max Memory Used | 39 MB | 37 MB | 39 MB | **100〜108 MB** |

**Init Duration は 38.7 MB の Layer でもほぼ変化しない（91.99 ms）。** Layer の内容は必要になった時点で読み込まれるため、初期化フェーズのコストにはほとんど現れない。実際のコストはハンドラ実行時に現れており、コールド時の Duration がウォーム時より約 1 秒長いのはこのためである。

> ハンドラの Duration が 2.6 秒台なのは、**検証のため両方式を各 3 回ずつ実行しているため**（OCR 6 回 + 初期化 + import）。単一方式・1 回の OCR であれば方式① で 200 ms 程度が見込まれる。

### Phase 3 まとめ

| 受入条件 | 判定 |
| --- | --- |
| 3-6 または 3-9 のいずれかで OCR に成功する | ✅ **両方成功** |
| 両方成功時は 3-11 の比較をもって本番採用方式を推奨する | ✅ 下記 |
| 解凍後 250 MB 以内 | ✅ 38.73 MB（余裕 211 MB） |

**Phase 3 完了。**

---

## 本番採用方式の推奨

**方式①（`ctypes` による C API 直接呼び出し）を推奨する。**

| 観点 | 方式① ctypes | 方式② pytesseract |
| --- | --- | --- |
| OCR 1 回あたり | **180.9 ms** | 613.2 ms（3.39 倍） |
| Layer サイズ | **約 15.3 MB** | 38.73 MB |
| Python 側の依存 | **なし** | pytesseract + Pillow |
| 初期化の再利用 | **可能**（ウォームスタートで効く） | 不可（毎回初期化） |
| 実装の手間 | 多い（`argtypes` / `restype` の宣言、メモリ解放） | **少ない** |
| 情報の得やすさ | 少ない | **多い** |

**判断根拠**: 性能差 3.39 倍とサイズ差 23 MB は、いずれも実装の手間という一度きりのコストを上回る。特に初期化コスト（432 ms）をウォームスタートで償却できる点が大きく、呼び出し頻度が上がるほど差が開く。

**方式②を選ぶべき場合**: 呼び出し頻度が低く（初期化コストが問題にならない）、実装・保守の容易さを優先する場合。その場合も Layer 構成は本検証のものをそのまま使える。

### 本番移行にあたっての申し送り

| # | 事項 |
| --- | --- |
| 1 | **言語データ**: 本検証は `tessdata_fast` の `eng` のみ（4.11 MB）。日本語や高精度版が必要な場合はサイズが増える。250 MB に対し 211 MB の余裕があるため、複数言語・`tessdata_best` でも収まる見込みだが、採用時に実測すること |
| 2 | **初期化ハンドルの再利用**: 方式①では `TessBaseAPI` ハンドルをハンドラ関数の外（モジュールスコープ）で保持し、ウォームスタート間で再利用すること。本検証のハンドラは検証目的のため毎回生成・破棄している |
| 3 | **`restype` の宣言漏れ**: Phase 1 で実測したとおり、宣言漏れは例外を出さず不正な値を返すため発見しにくい。ポインタを返す C API では必ず宣言すること |
| 4 | **OCR 精度**: 本検証はノイズのない単純な画像 1 枚での成立確認であり、精度の検証は行っていない |
| 5 | **メモリ**: Max Memory Used は 100〜108 MB。512 MB 設定に余裕があるが、大きな画像では増加するため実データで確認すること |

---

## 発生した問題と対処

| # | フェーズ | 事象 | 原因 | 対処 |
| --- | --- | --- | --- | --- |
| 1 | 0 | `finch vm init` でネットワーク依存関係のインストールに失敗 | `socket_vmnet` の配置に root 権限が必要 | ビルド用途では不要のためスキップ。VM 自体は正常起動しビルドも成立 |
| 2 | 0 | `invoke.sh` が `InvalidRequestContentException` で失敗 | デフォルトペイロードのシェル展開が `{\}` となり不正な JSON になっていた | デフォルト値の組み立てを修正 |
| 3 | 3 | AL2023 に `tesseract` / `leptonica` パッケージが存在しない | AL2023 のリポジトリに収録されていない | 公式アップストリームからのソースビルドに切り替え（§9-2 案 B） |
| 4 | 3 | Leptonica の CMake ビルドが `Target "leptonica" links to target "Threads::Threads" but the target was not found` で失敗 | 当環境の CMake 3.22.2 で `Threads::Threads` の解決に失敗 | Leptonica・Tesseract ともリリース同梱の autotools（`configure` / `autogen.sh`）に切り替え。`autoconf` / `automake` / `libtool` / `autoconf-archive` を追加導入 |
| 5 | 3 | `dnf list` が使えず、当初「ビルド依存もすべて MISSING」という誤った調査結果が出た | Lambda ベースイメージの `dnf` は機能が絞られた版で `list` 非対応。エラー出力が `grep` に吸われていた | フル `dnf` を持つ `amazonlinux:2023` で調べ直し、正しい提供状況を確認 |
