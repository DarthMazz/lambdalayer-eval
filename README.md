# lambdalayer-eval

LambdaLayer に配置した Native モジュールを Lambda の Python から呼び出す検証。

本番では OCR エンジン **Tesseract** の利用を想定し、その前段として
「Lambda Layer 上のネイティブモジュールを Python (`ctypes`) から呼べるか」を実 AWS 環境で検証する。

## ドキュメント

| 文書 | 内容 |
| --- | --- |
| [要件定義書](docs/requirements.md) | 目的、スコープ、検証フェーズ、受入条件、リスク |
| [検証結果レポート](docs/results.md) | フェーズごとの実測値、判定、発生した問題と対処 |
| 検証手順書 (`docs/procedure.md`) | 未作成 |

## 検証の概要

- **環境**: AWS `ap-northeast-1` / Lambda Python 3.13 / **arm64 (Graviton)**
- **デプロイ**: AWS CLI + シェルスクリプト（IaC は使用しない）
- **ビルド**: **Finch** で `public.ecr.aws/lambda/python:3.13` (linux/arm64) コンテナ内でビルド
- **呼び出し方式**: `ctypes` による `.so` 直接ロードを主軸とし、Phase 3 では `pytesseract` と比較

| フェーズ | 内容 | 状態 |
| --- | --- | --- |
| Phase 0 | 環境準備（Finch ビルド環境、IAM ロール、共通スクリプト、実行環境プローブ） | ✅ 完了 |
| Phase 1 | 依存なしの自作 `.so` を `ctypes` で呼ぶ（最小証明） | 未着手 |
| Phase 2 | 依存を持つ `.so` の解決確認 + `/opt/bin` 実行バイナリの補助確認 | 未着手 |
| Phase 3 | Tesseract 一式を Layer 化し、`ctypes` と `pytesseract` の両方式で OCR を実行 | 未着手 |

## 使い方

事前に Finch VM の起動と AWS へのログインが必要です。

```bash
finch vm start
```

```bash
./scripts/setup-role.sh
```

```bash
./scripts/build-layer.sh 1 && ./scripts/deploy.sh 1 && ./scripts/invoke.sh 1
```

検証で作成したリソースの削除:

```bash
./scripts/cleanup.sh --all
```

| スクリプト | 役割 |
| --- | --- |
| `scripts/config.sh` | 共通変数（リージョン、命名、ランタイム、ビルド環境） |
| `scripts/common.sh` | 共通関数 |
| `scripts/setup-role.sh` | IAM 実行ロールの作成 |
| `scripts/build-layer.sh` | コンテナ内で Layer をビルドし ZIP 化（aarch64 ELF を自動検証） |
| `scripts/deploy.sh` | Layer 発行 + 関数の作成／更新 |
| `scripts/invoke.sh` | invoke してレスポンスと実行ログを表示 |
| `scripts/cleanup.sh` | 作成リソースの削除 |

## 確認済みの実行環境（Phase 0 実測）

| 項目 | 値 |
| --- | --- |
| ビルド | Finch v1.17.2 / `public.ecr.aws/lambda/python:3.13` (linux/arm64) |
| ビルド環境 | Amazon Linux 2023 / aarch64 / glibc 2.34（gcc は `dnf install` が必要） |
| Lambda 実行環境 | Python 3.13.14 / aarch64 / **glibc 2.34（ビルド環境と一致）** |
| `LD_LIBRARY_PATH` | `/opt/lib` を含む ✅ |
| `PATH` | `/opt/bin` を含む ✅ |
| `sys.path` | `/opt/python`, `/opt/python/lib/python3.13/site-packages` を含む ✅ |
| 書き込み可能 | `/tmp` のみ（`/opt`・`/var/task` は読み取り専用） |
