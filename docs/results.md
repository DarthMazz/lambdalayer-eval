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
| Phase 1: 依存なし自作 `.so` | 未着手 | — |
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

## 発生した問題と対処

| # | 事象 | 原因 | 対処 |
| --- | --- | --- | --- |
| 1 | `finch vm init` でネットワーク依存関係のインストールに失敗 | `socket_vmnet` の配置に root 権限が必要 | ビルド用途では不要のためスキップ。VM 自体は正常起動しビルドも成立 |
| 2 | `invoke.sh` が `InvalidRequestContentException` で失敗 | デフォルトペイロードのシェル展開が `{\}` となり不正な JSON になっていた | デフォルト値の組み立てを修正 |
