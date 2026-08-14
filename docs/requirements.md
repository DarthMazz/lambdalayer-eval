# 要件定義書: Lambda Layer ネイティブモジュール呼び出し検証

| 項目 | 内容 |
| --- | --- |
| 文書バージョン | 1.1 |
| 作成日 | 2026-08-14 |
| 最終更新 | 2026-08-14（ビルド環境・実行方式を確定） |
| 対象リポジトリ | `lambdalayer-eval` |
| ステータス | 確定（残る未決事項は §9） |

---

## 1. 背景と目的

### 1.1 背景

本番システムにおいて、AWS Lambda (Python) から OCR エンジン **Tesseract** を利用したい。
Tesseract は Python の純粋実装ではなくネイティブ（C/C++）モジュールであるため、Lambda の実行環境に対して以下を解決する必要がある。

- ネイティブバイナリ／共有ライブラリをどこに配置するか
- Python プロセスからどう解決・ロードするか
- Lambda のパッケージサイズ制約に収まるか

**Lambda Layer** に配置する方式が有力だが、実運用前に動作可否と制約を実機で確認しておきたい。

### 1.2 目的

本検証の目的は次の 1 点に集約される。

> **Lambda Layer に配置したネイティブモジュールを、Lambda の Python ランタイムから `ctypes` 経由で呼び出せることを、実 AWS 環境で確認する。**

加えて、本番（Tesseract）適用時に問題となりうる制約・所要サイズ・コールドスタート影響を定量的に把握し、後続の実装判断の根拠を残す。

### 1.3 本検証で答えを出したい問い

| # | 問い | 確認フェーズ |
| --- | --- | --- |
| Q1 | Layer に置いた `.so` を Python の `ctypes` でロードして関数呼び出しできるか | Phase 1 |
| Q2 | `LD_LIBRARY_PATH` の追加設定なしに `/opt/lib` の `.so` が解決されるか | Phase 1 |
| Q3 | `.so` が別の `.so` に依存する場合、依存解決は成立するか（芋づる依存） | Phase 2 |
| Q4 | 実行バイナリを `/opt/bin` に置いた場合 `subprocess` から起動できるか（補助確認） | Phase 2 |
| Q5 | Tesseract 一式（libtesseract + leptonica + 言語データ）を Layer に収められるか | Phase 3 |
| Q6 | Lambda 上で実際に OCR 結果（テキスト）が得られるか | Phase 3 |
| Q7 | Layer サイズ・解凍後サイズ・コールドスタート時間はどの程度か | 全フェーズ |

---

## 2. スコープ

### 2.1 対象（In Scope）

- Lambda Layer の作成・発行（`aws lambda publish-layer-version`）
- Lambda 関数の作成・Layer アタッチ・実行（`aws lambda create-function` / `invoke`）
- Python から `ctypes` によるネイティブライブラリのロードと関数呼び出し
- ネイティブライブラリの依存関係解決の確認
- Tesseract による最小限の OCR 実行（英語 1 言語、単純な画像 1 枚）
- 上記の再現手順・結果のドキュメント化

### 2.2 対象外（Out of Scope）

以下は本検証では扱わない。本番実装時に別途検討する。

- 本番相当の OCR 精度チューニング、前処理、複数言語対応
- コンテナイメージ形式の Lambda（本検証は zip + Layer 方式に限定）
- API Gateway / S3 イベント等のトリガー連携
- CI/CD パイプライン、IaC（SAM/CDK/Terraform）による恒久的な管理
- VPC 配置、暗号化、本番相当のセキュリティ設計
- 同時実行数・スループットの負荷試験
- x86_64 アーキテクチャでの動作確認（arm64 に限定）

---

## 3. 前提条件

### 3.1 AWS 環境

| 項目 | 値 |
| --- | --- |
| AWS アカウント | `543803375852` |
| 実行 IAM プリンシパル | `arn:aws:iam::543803375852:user/ma2moto` |
| リージョン | `ap-northeast-1`（東京） |
| 検証方法 | 実 AWS 環境へデプロイして実行（ローカルエミュレータは使用しない） |

### 3.2 Lambda 実行環境

| 項目 | 値 | 備考 |
| --- | --- | --- |
| ランタイム | Python 3.13 | Amazon Linux 2023 ベース |
| アーキテクチャ | **arm64 (Graviton)** | ライブラリは `aarch64` でビルドすること |
| メモリ | 512 MB（初期値、計測結果により調整） | |
| タイムアウト | 30 秒（Phase 3 は 60 秒） | |

### 3.3 デプロイ方式

**AWS CLI + シェルスクリプト**を用いる。IaC ツール（SAM / CDK / Terraform）は使用しない。

- 理由: 検証対象が「Layer の中身と Lambda 実行環境の挙動」であり、IaC を挟むと抽象化によって実際に何が起きているかが見えにくくなるため。手順が素の API 呼び出しとして残ることを優先する。
- すべての操作は `scripts/` 配下の冪等なシェルスクリプトとして記述し、手作業（マネジメントコンソール操作）を残さない。

### 3.4 ビルド環境

Lambda の実行環境は Amazon Linux 2023 / aarch64 / glibc であり、生成物は **ELF 形式**である必要がある。
macOS の clang が生成するのは Mach-O 形式であり Lambda では一切ロードできないため、**実行環境と同一の Linux コンテナ内でビルドする**。

| 項目 | 内容 |
| --- | --- |
| コンテナランタイム | **Finch**（`brew install --cask finch` で導入済み、v1.17.2） |
| ビルドイメージ | `public.ecr.aws/lambda/python:3.13`（Lambda 実行環境と同一）を基本とする。コンパイラ等の導入が必要な場合は `amazonlinux:2023` を併用 |
| プラットフォーム | `linux/arm64` |
| 備考 | ホストが Apple Silicon (arm64) のため、エミュレーションなしのネイティブビルドとなる |

ビルドは以下の形でコンテナ内に閉じて実行し、成果物のみをホストへ取り出す。

```
finch run --rm --platform linux/arm64 -v "$PWD:/work" -w /work <image> <build command>
```

### 3.5 呼び出し方式

**`ctypes` による `.so` の直接ロードを主方式**とし、**Phase 3 では `pytesseract`（subprocess 方式）も併せて検証して比較する**（採用案: B）。

| フェーズ | 方式 |
| --- | --- |
| Phase 1・2 | `ctypes.CDLL()` による自作共有ライブラリのロードと関数呼び出し |
| Phase 2（補助） | `/opt/bin` 配置の実行バイナリを `subprocess` から起動 |
| Phase 3 | **① `ctypes` で `libtesseract.so` の C API を直接呼ぶ**、**② `pytesseract` から `tesseract` 実行ファイルを呼ぶ** の両方を同一 Layer 上で実行し比較する |

**両方式を併せて検証する理由**

- Layer には `libtesseract.so` が必須であり（CLI 自身がリンクしているため）、追加で必要なのは実行ファイル `tesseract` と Python パッケージのみ。**追加コストが小さい**
- 「`ctypes` は高速だが実装が重い」「`pytesseract` は実装が容易だがプロセス起動コストが乗る」というトレードオフを、**実測値で比較して本番方式を決定できる**
- 一方が不成立でも他方で目的（Lambda 上での OCR 実行）を達成でき、検証が空振りにならない

なお Tesseract は C++ 実装だが **C API (`capi.h` 相当、`TessBaseAPI*` 系関数)** が公開されているため、`ctypes` からの呼び出しが可能である。

### 3.6 検証に用いる Lambda Layer の既知仕様（検証で追認する前提知識）

| 項目 | 内容 |
| --- | --- |
| 展開先 | Layer の ZIP 内容は実行環境の `/opt` 配下に展開される |
| 共有ライブラリ探索 | Python ランタイムの `LD_LIBRARY_PATH` に `/opt/lib` が含まれる |
| 実行ファイル探索 | `PATH` に `/opt/bin` が含まれる |
| Python パッケージ | `/opt/python` および `/opt/python/lib/python3.13/site-packages` が `sys.path` に含まれる |
| Layer 数上限 | 1 関数あたり最大 5 レイヤー |
| サイズ上限 | 関数コード + 全 Layer の**解凍後合計 250 MB** |
| アップロード | ZIP 直接アップロードは 50 MB まで。超える場合は S3 経由（`--content S3Bucket=...`） |
| 書き込み可能領域 | `/tmp`（既定 512 MB）。`/opt` および `/var/task` は読み取り専用 |

> これらは AWS のドキュメント上の仕様であり、**本検証では「そうなっているはず」ではなく実測で確認する**。特に `/opt/lib` の自動解決（Q2）は Phase 1 の主要な確認項目とする。

---

## 4. 検証フェーズ

段階的に難易度を上げ、失敗時に原因を切り分けられる構成とする。各フェーズは前フェーズの成功を前提とする。

```
Phase 0  環境準備
   ↓
Phase 1  依存なし自作 .so        … 「Layer に置いた .so を ctypes で呼べるか」の最小証明
   ↓
Phase 2  依存あり .so + 実行バイナリ … 依存解決と PATH/LD_LIBRARY_PATH の挙動確認
   ↓
Phase 3  Tesseract 一式          … 本番相当の成立性確認
```

---

### Phase 0: 環境準備

**目的**: 以降のフェーズを実行できる状態を整える。

| # | 作業 |
| --- | --- |
| 0-1 | Finch VM を初期化・起動する（`finch vm init` / `finch vm start`） |
| 0-2 | `linux/arm64` のビルドイメージを取得し、コンテナ内でのコンパイルが通ることを確認する |
| 0-3 | Lambda 実行ロール（`AWSLambdaBasicExecutionRole` のみ付与）を作成する |
| 0-4 | 共通変数（リージョン、アカウント ID、命名プレフィックス）を定義した設定ファイルを作成する |
| 0-5 | Layer 発行・関数作成・invoke・クリーンアップの共通シェル関数を用意する |

**成功基準**

- Finch のコンテナ内で `aarch64` の ELF 共有ライブラリが生成できる。ホスト側から `file` コマンドで `ELF 64-bit LSB shared object, ARM aarch64` と判定されること。
- Layer を含まない「Hello World」Lambda 関数を CLI のみでデプロイ・invoke でき、正常応答が得られる。

**Finch に関する留意点**

- `finch vm init` の過程で、コンテナの公開ポートを macOS 側から参照するためのネットワーク設定（`socket_vmnet`）に **root 権限が要求される**。本検証ではコンテナを**ビルド用途でのみ**使用し、ポート公開を行わないため、**この設定は不要**であり未設定のまま進行してよい。
- ホスト・コンテナ間のファイル受け渡しはボリュームマウント（`-v`）で行う。

---

### Phase 1: 依存なしの自作共有ライブラリ

**目的**: 「Layer に配置したネイティブモジュールを Python から呼べるか」という本検証の核心を、最小構成で証明する。

**検証対象**

C 言語で記述した外部依存のない共有ライブラリ。最低限、以下 2 種類の関数を持たせる。

| 関数 | シグネチャ | 確認内容 |
| --- | --- | --- |
| 整数演算 | `int add(int a, int b)` | 基本的な呼び出しと戻り値 |
| 文字列返却 | `const char* version(void)` | ポインタ返却と Python 側での文字列デコード |

**成果物**

```
layers/phase1/
├── src/libeval.c
├── build.sh              # aarch64 向けにコンパイルし lib/libeval.so を生成
└── (生成) layer.zip      # 内部構造: lib/libeval.so
functions/phase1/
└── handler.py            # ctypes でロードして呼び出し、結果を返す
```

**検証項目と成功基準**

| # | 検証項目 | 成功基準 |
| --- | --- | --- |
| 1-1 | Layer 発行 | `publish-layer-version` が成功し、LayerVersionArn が得られる |
| 1-2 | `/opt` への展開 | ハンドラ内で `os.listdir("/opt")` および `/opt/lib` の内容を出力し、`libeval.so` の存在を確認できる |
| 1-3 | **絶対パス指定でのロード** | `ctypes.CDLL("/opt/lib/libeval.so")` が例外なく成功する |
| 1-4 | **ライブラリ名のみでのロード（Q2）** | `ctypes.CDLL("libeval.so")` が成功する（= `LD_LIBRARY_PATH` に `/opt/lib` が含まれることの実証） |
| 1-5 | 関数呼び出し | `add(2, 3)` が `5` を返す |
| 1-6 | 文字列返却 | `version()` の戻り値を UTF-8 デコードして期待値と一致する |
| 1-7 | 環境情報の記録 | `LD_LIBRARY_PATH` / `PATH` / `platform.machine()` / `sys.version` をログ出力し、実測値を文書に記録する |

**Phase 1 の受入条件**: 1-3 と 1-5 が成功すること（本検証の最低到達点）。1-4 が失敗する場合は、明示的に `LD_LIBRARY_PATH` を設定するか絶対パス指定が必要、という制約として記録する。

---

### Phase 2: 依存関係を持つライブラリと実行バイナリ

**目的**: Tesseract のように**他の共有ライブラリに依存する**ケースで、依存解決が成立するかを確認する。Phase 1 と Phase 3 の間にあるギャップ（依存解決の失敗）を先に潰す。

**検証対象**

1. **依存あり `.so`**: Phase 1 の `libeval.so` を、別の自作ライブラリ `libevaldep.so` に依存させる（`libeval.so` → `libevaldep.so`）。両方を Layer の `lib/` に配置する。
2. **実行バイナリ（補助）**: `/opt/bin` に単純な実行ファイルを配置し、`subprocess.run()` から起動する。

**検証項目と成功基準**

| # | 検証項目 | 成功基準 |
| --- | --- | --- |
| 2-1 | 依存 `.so` の自動解決（Q3） | `ctypes.CDLL("/opt/lib/libeval.so")` が、依存する `libevaldep.so` も含めて解決され成功する |
| 2-2 | 依存関係の可視化 | ハンドラ内で依存関係を確認できる情報（`/proc/self/maps` のロード済みライブラリ一覧など）を出力し、`/opt/lib` 配下がマップされていることを確認する |
| 2-3 | 解決失敗時の挙動記録 | 依存 `.so` を意図的に除外した Layer を作り、発生するエラーメッセージ（`OSError: ... cannot open shared object file`）を記録する |
| 2-4 | 実行バイナリ起動（Q4、補助） | `/opt/bin` 配置のバイナリが `subprocess` から起動し、標準出力を取得できる |
| 2-5 | 実行権限 | ZIP 化時にパーミッション（`0755`）が保持されることを確認する |

**Phase 2 の受入条件**: 2-1 が成功すること。2-3 は「失敗パターンの記録」であり、失敗すること自体が成果である。

---

### Phase 3: Tesseract（本番想定）

**目的**: 本番で採用する Tesseract について、Layer 方式での成立性とサイズ制約を確認する。
あわせて **`ctypes` 方式と `pytesseract` 方式を同一 Layer 上で実行して比較**し、本番採用方式の判断材料を得る。

**Layer 構成（両方式を 1 つの Layer に同梱する）**

```
layer.zip
├── bin/
│   └── tesseract                  # 実行ファイル（pytesseract 方式で使用）
├── lib/
│   ├── libtesseract.so            # 本体。両方式で必要（CLI 自身がリンクしているため）
│   ├── libleptonica.so            # 画像処理ライブラリ
│   └── ...                        # 間接依存（libjpeg/libpng/libtiff/libwebp/libz/
│                                  #   libstdc++/libgomp 等。実測で洗い出す）
├── tessdata/
│   └── eng.traineddata            # Phase 3 では英語のみ
└── python/
    ├── pytesseract/               # 純 Python
    └── PIL/                       # Pillow。arm64 wheel を取得すること
```

> Python パッケージは、macOS 上で通常の `pip install -t` を行うと macOS 向けの成果物が入り Lambda で動作しない。
> Finch のコンテナ内でインストールするか、`--platform manylinux2014_aarch64 --only-binary=:all:` を指定して取得する。

**方式 ① — `ctypes` による C API 直接呼び出し**

`ctypes` で `libtesseract.so` をロードし、以下の流れで OCR を実行する。

1. `TessBaseAPICreate()` で API ハンドルを生成
2. `TessBaseAPIInit3(handle, tessdata_path, "eng")` で初期化（言語データのパスを引数で明示指定）
3. Leptonica の `pixRead()` で画像を読み込み、`TessBaseAPISetImage2()` に渡す
4. `TessBaseAPIGetUTF8Text()` で認識結果を取得
5. `TessDeleteText()` / `TessBaseAPIDelete()` で解放

> 各関数の `argtypes` / `restype` を明示的に宣言する。特にポインタ返却関数で `restype` を宣言しないと 64bit ポインタが切り詰められるため、必ず設定する。

**方式 ② — `pytesseract` による実行ファイル呼び出し**

```python
pytesseract.pytesseract.tesseract_cmd = "/opt/bin/tesseract"
```

を設定したうえで `image_to_string()` を呼ぶ。pytesseract は入力画像を一時ファイルへ書き出すため、書き込み先が `/tmp` になっていることを確認する（`/opt`・`/var/task` は読み取り専用）。

**入力データ**

- 両方式で**同一の画像**を用いる。ノイズのない単純な画像 1 枚（例: 白背景に黒字で `"HELLO LAMBDA"` を描画した PNG）
- 画像は関数コード側に同梱する

**検証項目と成功基準**

| # | 検証項目 | 成功基準 |
| --- | --- | --- |
| 3-1 | Layer サイズ | ZIP サイズ・解凍後サイズを実測し、**解凍後 250 MB 以内**に収まることを確認する |
| 3-2 | アップロード方式 | ZIP が 50 MB を超える場合、S3 経由での `publish-layer-version` が成功する |
| 3-3 | ライブラリロード | `ctypes.CDLL` で `libtesseract.so` のロードに成功する |
| 3-4 | バージョン取得（早期ゲート） | `TessVersion()` を呼び出し、Tesseract のバージョン文字列が取得できる |
| 3-5 | 言語データ解決 | `TessBaseAPIInit3` が戻り値 `0`（成功）を返す。`TESSDATA_PREFIX` 環境変数と引数指定のどちらが必要かを記録する（バージョンにより `TESSDATA_PREFIX` の指す階層が異なるため） |
| 3-6 | **① ctypes での OCR 実行（Q6）** | サンプル画像から期待するテキストが取得できる |
| 3-7 | 実行ファイルの疎通 | `subprocess` で `/opt/bin/tesseract --version` が成功する |
| 3-8 | Python パッケージの import | `/opt/python` から `pytesseract` と `PIL` が import できる |
| 3-9 | **② pytesseract での OCR 実行** | 同一画像から ① と同等のテキストが取得できる |
| 3-10 | 一時ファイル書き込み | pytesseract 実行時に読み取り専用領域への書き込みエラーが発生しない |
| 3-11 | **両方式の性能比較** | 同一 invoke 内で ①② を実行し、それぞれの所要時間を計測・比較する |
| 3-12 | リソース計測 | コールドスタート時の所要時間・使用メモリ（`REPORT` ログの `Init Duration` / `Max Memory Used`）を記録する |
| 3-13 | ウォームスタート | 2 回目以降の invoke の実行時間を記録し、初期化コストを分離して把握する |

**Phase 3 の受入条件**

- **3-6 または 3-9 のいずれかが成功すること**（Lambda 上で OCR が実行できたことの証明）。
- 両方成功した場合は 3-11 の比較結果をもって本番採用方式を推奨する。
- 片方のみ成功した場合は、失敗側の原因と切り分け結果を記録し、成功した方式を採用方針とする。
- 3-1 で 250 MB を超過した場合は、超過分の実測値と削減候補（言語データの絞り込み、不要ライブラリの除去、`strip` 適用、方式を片方に絞る等）を記録し、**コンテナイメージ方式への切り替え要否**を判断材料として残す。

---

## 5. 計測項目

全フェーズで以下を記録し、結果レポートに一覧化する。

| 指標 | 取得元 |
| --- | --- |
| Layer ZIP サイズ | ローカルファイルサイズ |
| Layer 解凍後サイズ | `publish-layer-version` のレスポンス、または展開後の実測 |
| コールドスタート時間 | CloudWatch Logs の `REPORT` 行の `Init Duration` |
| 実行時間（コールド / ウォーム） | `REPORT` 行の `Duration` |
| 最大メモリ使用量 | `REPORT` 行の `Max Memory Used` |
| ライブラリロード時間 | ハンドラ内で `ctypes.CDLL` 前後の時刻差を計測 |

---

## 6. 成果物

| 成果物 | パス | 内容 |
| --- | --- | --- |
| 要件定義書 | `docs/requirements.md` | 本書 |
| 検証手順書 | `docs/procedure.md` | 環境構築からデプロイ・実行までの再現手順 |
| 検証結果レポート | `docs/results.md` | フェーズごとの結果、実測値、エラーと対処、結論 |
| ビルド／デプロイスクリプト | `scripts/` | Layer ビルド、発行、関数作成、invoke、クリーンアップ |
| Layer ソース | `layers/phase{1,2,3}/` | C ソース、ビルド定義 |
| Lambda 関数コード | `functions/phase{1,2,3}/` | `handler.py` |

想定ディレクトリ構成:

```
lambdalayer-eval/
├── README.md
├── docs/
│   ├── requirements.md
│   ├── procedure.md
│   └── results.md
├── scripts/
│   ├── config.sh          # リージョン・アカウント・命名の共通変数
│   ├── common.sh          # 共通シェル関数
│   ├── build-layer.sh     # <phase> を引数に取り layer.zip を生成
│   ├── deploy.sh          # Layer 発行 + 関数作成/更新
│   ├── invoke.sh          # invoke して結果とログを表示
│   └── cleanup.sh         # 作成したリソースを削除
├── layers/
│   ├── phase1/
│   ├── phase2/
│   └── phase3/
└── functions/
    ├── phase1/handler.py
    ├── phase2/handler.py
    └── phase3/handler.py
```

---

## 7. 命名規約

作成する AWS リソースは、検証後に一括削除できるよう共通プレフィックスを付ける。

| リソース | 命名 |
| --- | --- |
| プレフィックス | `lleval` |
| Layer | `lleval-phase{N}-layer` |
| Lambda 関数 | `lleval-phase{N}-fn` |
| IAM ロール | `lleval-lambda-role` |
| S3 バケット（必要時） | `lleval-artifacts-543803375852-ap-northeast-1` |
| CloudWatch ロググループ | `/aws/lambda/lleval-phase{N}-fn`（自動生成） |

---

## 8. 制約・リスク

| # | リスク | 影響 | 対応方針 |
| --- | --- | --- | --- |
| R1 | ~~ビルド環境がローカルに無い~~ | — | **解消済み（2026-08-14）**。Finch を導入し、arm64 ELF の生成をホスト側から検証済み（§9-1） |
| R2 | glibc バージョン不一致 | `.so` ロード時に `GLIBC_2.xx not found` | 実行環境と同一の Amazon Linux 2023（glibc 2.34）でビルドする。Lambda 実行環境と同じイメージを使うため発生可能性は低い |
| R2b | Python パッケージを macOS 上で `pip install` してしまう | Lambda で import に失敗 | Finch のコンテナ内でインストールするか `--platform manylinux2014_aarch64 --only-binary=:all:` を指定する（Pillow 等の C 拡張が対象） |
| R3 | Tesseract 一式が 250 MB を超過 | Phase 3 の受入条件未達 | 言語データを `eng` のみに限定、`strip` によるシンボル削減、不要ライブラリの除去。それでも超過する場合はコンテナイメージ方式を代替案として提示 |
| R4 | 依存 `.so` の芋づる漏れ | ロード時エラー | `ldd` で再帰的に依存を洗い出し、Layer に同梱。Phase 2 で先行して検証パターンを確立する |
| R5 | Tesseract の C API が期待どおり公開されていない | 方式 ①（`ctypes`）が成立しない | Phase 3 の 3-4（`TessVersion` 呼び出し）を早期のゲートとする。不成立でも方式 ②（`pytesseract`）を**同一 Layer に同梱済み**のため、Layer を作り直すことなく切り替えられる |
| R6 | コールドスタートが実用に耐えない | 本番採用の妨げ | 3-7 / 3-8 で定量化し、プロビジョンド同時実行等の要否判断材料として記録する |
| R7 | 検証リソースの消し忘れによる課金 | 軽微 | `scripts/cleanup.sh` を用意し、各フェーズ完了時に実行する |

---

## 9. 未決事項

### 9-1. arm64 ビルド環境の確保方法 — **決定済み（2026-08-14）**

**Finch を採用**。§3.4 に確定内容を記載。以下のとおり動作確認済みであり、本項目は解消とする。

| 確認項目 | 実測結果 |
| --- | --- |
| Finch バージョン | v1.17.2 |
| VM 状態 | `Running`（`finch vm init` 完了） |
| ビルドイメージ | `public.ecr.aws/lambda/python:3.13` |
| アーキテクチャ | `aarch64` |
| OS | Amazon Linux 2023 |
| glibc | 2.34 |
| コンパイラ | イメージに **gcc は未同梱**。`dnf install -y gcc` で導入する（`dnf` / `microdnf` は利用可能） |
| ホスト⇔コンテナのファイル共有 | ボリュームマウント（`-v`）で双方向に成立 |
| 生成物の検証 | コンテナ内で生成した `.so` をホストの `file` で判定し、`ELF 64-bit LSB shared object, ARM aarch64` を確認 |

**既知の制約**

- `finch vm init` 時、コンテナの公開ポートを macOS 側から参照するためのネットワーク設定（`socket_vmnet`）で root 権限が要求され、これは**未設定のままとしている**。本検証はビルド用途のみでポート公開を行わないため影響はない。将来コンテナのポートへホストから接続する必要が生じた場合は、別途 `sudo` を伴う設定が必要になる。
- ビルド成果物のオーナーが `root` になるため、ZIP 化前にパーミッション（読み取り可・実行ファイルは `0755`）を確認する。

### 9-2. Tesseract バイナリの入手方法（Phase 3 開始前に決定）

| 案 | 内容 |
| --- | --- |
| A. Amazon Linux 2023 の `dnf` で導入し、`/usr/lib64` から必要な `.so` を収集 | 手順が単純。パッケージの提供状況を Phase 3 着手時に確認する |
| B. ソースからビルド | 依存を最小化でき、サイズ削減に有利。ビルド時間と手間が増える |
| C. 既存の公開 Layer / ビルド済み成果物を利用 | 最速だが、提供元の信頼性と arm64 対応の確認が必要 |

Phase 3 着手時に A を第一候補として調査し、サイズ超過（R3）が発生した場合に B を検討する。

---

## 10. 完了条件

本検証は、以下をすべて満たした時点で完了とする。

1. Phase 1 の受入条件を満たし、**Layer 上のネイティブモジュールを Python から呼び出せることが実 AWS 環境で実証されている**。
2. Phase 2 の受入条件を満たし、依存関係を持つライブラリでも成立することが確認されている。
3. Phase 3 について、方式 ①（`ctypes`）または ②（`pytesseract`）の**いずれかで OCR 実行に成功している**か、**または**両方不成立の理由と代替案（コンテナイメージ方式等）が定量的根拠とともに記録されている。
4. 両方式が成功した場合、性能比較の結果に基づく**本番採用方式の推奨**が示されている。
4. `docs/procedure.md` に従えば第三者が同じ結果を再現できる。
5. `docs/results.md` に §5 の計測値と、発生したエラー・対処が記録されている。
6. `scripts/cleanup.sh` により検証リソースが削除されている。
