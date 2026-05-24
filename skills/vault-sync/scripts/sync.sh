#!/bin/bash
# vault-sync.sh
# Vault を Git remote 経由で複数マシン間で同期するスクリプト
# 想定: cron / launchd 等から定期実行（例: 10 分ごと）

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# .env を読み込む（あれば）
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

VAULT_DIR="${VAULT_PATH:-$REPO_ROOT/vault}"
LOG_FILE="${VAULT_SYNC_LOG:-$REPO_ROOT/logs/vault-sync.log}"
GIT="${GIT_BIN:-git}"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$(dirname "$LOG_FILE")"

# vault ディレクトリに移動（失敗したら終了）
cd "$VAULT_DIR" || { echo "[$TIMESTAMP] ERROR: vault dir not found: $VAULT_DIR" >> "$LOG_FILE"; exit 1; }

# 最新を取得（rebase: マージコミットを作らない / autostash: ローカル変更を一時退避）
$GIT pull --rebase --autostash origin main >> "$LOG_FILE" 2>&1

# ID 衝突検出・自動修復（cross-machine race 対策）
python3 "$SCRIPT_DIR/detect_id_collisions.py" --pretty >> "$LOG_FILE" 2>&1

# 変更があればコミット＆プッシュ
if ! $GIT diff --quiet \
    || ! $GIT diff --cached --quiet \
    || [ -n "$($GIT ls-files --others --exclude-standard)" ]; then
    $GIT add -A
    $GIT commit -m "auto-sync: $TIMESTAMP" >> "$LOG_FILE" 2>&1
    $GIT push origin main >> "$LOG_FILE" 2>&1
    echo "[$TIMESTAMP] Pushed changes" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] No changes" >> "$LOG_FILE"
fi
