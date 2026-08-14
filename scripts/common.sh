#!/usr/bin/env bash
# 各スクリプトから利用する共通関数。config.sh を読み込んだ上で source する。

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() {
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "コマンドが見つかりません: $c"
  done
}

# 呼び出し元アカウント ID を取得（キャッシュする）
account_id() {
  if [ -z "${_ACCOUNT_ID:-}" ]; then
    _ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)" \
      || die "AWS 認証情報を取得できません。aws sso login などでログインしてください。"
  fi
  printf '%s' "$_ACCOUNT_ID"
}

role_arn() { printf 'arn:aws:iam::%s:role/%s' "$(account_id)" "$ROLE_NAME"; }

layer_name()    { printf '%s-phase%s-layer' "$PREFIX" "$1"; }
function_name() { printf '%s-phase%s-fn' "$PREFIX" "$1"; }

# フェーズ番号の妥当性チェック
require_phase() {
  case "${1:-}" in
    0|1|2|3) : ;;
    *) die "フェーズ番号を 0〜3 で指定してください（指定値: '${1:-未指定}'）" ;;
  esac
}

# Lambda 関数が存在するか
function_exists() {
  aws lambda get-function --function-name "$1" >/dev/null 2>&1
}

# 関数の更新が完了するまで待つ（連続更新時の ResourceConflictException 回避）
wait_function_ready() {
  aws lambda wait function-updated-v2 --function-name "$1" 2>/dev/null || true
}

# ビルド用コンテナでコマンドを実行する。
# 第1引数: ホスト側のマウント元ディレクトリ（/work にマウントされる）
# 第2引数以降: コンテナ内で実行するシェルコマンド
run_in_builder() {
  mount_dir="$1"; shift
  [ -d "$mount_dir" ] || die "マウント対象が存在しません: $mount_dir"
  "$CONTAINER_CMD" run --rm \
    --platform "$BUILD_PLATFORM" \
    --entrypoint /bin/sh \
    -v "${mount_dir}:/work" \
    -w /work \
    "$BUILD_IMAGE" -c "$*"
}
