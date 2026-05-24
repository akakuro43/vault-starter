#!/usr/bin/env bash
# bootstrap.sh — vault-starter 初期セットアップ
#
# 役割:
#   1. uv の存在確認
#   2. .env の作成 (なければ .env.example からコピー)
#   3. Python 仮想環境 + 依存インストール (uv venv + uv pip install)
#   4. ランタイム用ディレクトリ作成 (logs/, credentials/, vault/00_inbox/...)
#   5. vault/ が git repo でない場合の git init (vault-sync で同期したい場合のために)
#
# Idempotent: 何度実行しても安全。

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
REPO_ROOT="$(pwd)"

echo "== vault-starter bootstrap =="
echo "  repo: $REPO_ROOT"
echo ""

# ── 1. uv 確認 ────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv が見つかりません"
  echo "  install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "  詳細:   https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
echo "OK uv $(uv --version | awk '{print $2}')"

# ── 2. .env ───────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "OK created .env from .env.example"
  echo "   → .env を編集して GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID 等を設定してください"
else
  echo "OK .env exists (skip)"
fi

# ── 3. Python 仮想環境 ──────────────────────────────────────
if [ ! -d .venv ]; then
  echo "  creating Python venv..."
  uv venv
fi
echo "OK .venv exists"

# ── 4. 依存インストール ─────────────────────────────────────
echo "  installing dependencies..."
uv pip install -r requirements.txt --quiet
echo "OK dependencies installed"

# ── 5. ランタイム用ディレクトリ ─────────────────────────────
mkdir -p logs credentials vault/00_inbox/meeting_transcripts
echo "OK runtime dirs ready (logs/, credentials/, vault/00_inbox/meeting_transcripts/)"

# ── 6. vault/ を git repo として初期化 (vault-sync 用) ───────
if [ ! -d vault/.git ]; then
  echo "  (info) vault/ is not a git repo yet."
  echo "         vault-sync を使う場合は vault/ で 'git init' + remote 設定が必要です。"
fi

# ── 完了メッセージ ───────────────────────────────────────────
cat <<'EOF'

== bootstrap complete ==

Next steps:

  1. .env を編集
     - GOOGLE_DRIVE_TRANSCRIPT_FOLDER_ID  (Drive のフォルダ ID)
     - NOTIFICATION_SINK                   (discord | slack | stdout | file)
     - DISCORD_WEBHOOK_URL or SLACK_WEBHOOK_URL  (sink によって)
     - YOUR_EMAIL_DOMAINS, YOUR_ORGANIZATIONS

  2. Google Drive OAuth credentials を配置
     - credentials/google-drive.json
       (Google Cloud Console で OAuth 2.0 Client ID を作成してダウンロード)

  3. 認証テスト (ブラウザが開きます)
     source .venv/bin/activate
     python3 skills/mtg-importer/scripts/auth_test.py

  4. 初回トランスクリプト取り込み (seed モード — 既存ファイル記録のみ)
     python3 skills/mtg-importer/scripts/fetch_transcripts.py

詳細は README.md と docs/ を参照してください。
EOF
